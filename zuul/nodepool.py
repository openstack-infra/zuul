# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging

from zuul import model
from zuul.zk import LockException


class Nodepool(object):
    log = logging.getLogger('zuul.nodepool')

    def __init__(self, scheduler):
        self.requests = {}
        self.sched = scheduler

    def emitStats(self, request):
        # Implements the following :
        #  counter zuul.nodepool.requests.<state>.total
        #  counter zuul.nodepool.requests.<state>.label.<label>
        #  counter zuul.nodepool.requests.<state>.size.<size>
        #  timer   zuul.nodepool.requests.(fulfilled|failed)
        #  timer   zuul.nodepool.requests.(fulfilled|failed).<label>
        #  timer   zuul.nodepool.requests.(fulfilled|failed).<size>
        #  gauge   zuul.nodepool.current_requests
        if not self.sched.statsd:
            return
        statsd = self.sched.statsd
        pipe = statsd.pipeline()
        state = request.state
        dt = None

        if request.canceled:
            state = 'canceled'
        elif request.state in (model.STATE_FULFILLED, model.STATE_FAILED):
            dt = int((request.state_time - request.requested_time) * 1000)

        key = 'zuul.nodepool.requests.%s' % state
        pipe.incr(key + ".total")

        if dt:
            pipe.timing(key, dt)
        for node in request.nodeset.getNodes():
            pipe.incr(key + '.label.%s' % node.label)
            if dt:
                pipe.timing(key + '.label.%s' % node.label, dt)
        pipe.incr(key + '.size.%s' % len(request.nodeset.nodes))
        if dt:
            pipe.timing(key + '.size.%s' % len(request.nodeset.nodes), dt)
        pipe.gauge('zuul.nodepool.current_requests', len(self.requests))
        pipe.send()

    def requestNodes(self, build_set, job, relative_priority):
        # Create a copy of the nodeset to represent the actual nodes
        # returned by nodepool.
        nodeset = job.nodeset.copy()
        req = model.NodeRequest(self.sched.hostname, build_set, job,
                                nodeset, relative_priority)
        self.requests[req.uid] = req

        if nodeset.nodes:
            self.sched.zk.submitNodeRequest(req, self._updateNodeRequest)
            # Logged after submission so that we have the request id
            self.log.info("Submitted node request %s" % (req,))
            self.emitStats(req)
        else:
            self.log.info("Fulfilling empty node request %s" % (req,))
            req.state = model.STATE_FULFILLED
            self.sched.onNodesProvisioned(req)
            del self.requests[req.uid]
        return req

    def cancelRequest(self, request):
        self.log.info("Canceling node request %s" % (request,))
        if request.uid in self.requests:
            request.canceled = True
            try:
                self.sched.zk.deleteNodeRequest(request)
            except Exception:
                self.log.exception("Error deleting node request:")

    def reviseRequest(self, request, relative_priority=None):
        '''Attempt to update the node request, if it is not currently being
        processed.

        :param: NodeRequest request: The request to update.
        :param relative_priority int: If supplied, the new relative
            priority to set on the request.

        '''
        if relative_priority is None:
            return
        try:
            self.sched.zk.lockNodeRequest(request, blocking=False)
        except LockException:
            # It may be locked by nodepool, which is fine.
            self.log.debug("Unable to revise locked node request %s", request)
            return False
        try:
            old_priority = request.relative_priority
            request.relative_priority = relative_priority
            self.sched.zk.storeNodeRequest(request)
            self.log.debug("Revised relative priority of "
                           "node request %s from %s to %s",
                           request, old_priority, relative_priority)
        except Exception:
            self.log.exception("Unable to update node request %s", request)
        finally:
            try:
                self.sched.zk.unlockNodeRequest(request)
            except Exception:
                self.log.exception("Unable to unlock node request %s", request)

    def holdNodeSet(self, nodeset, autohold_key):
        '''
        Perform a hold on the given set of nodes.

        :param NodeSet nodeset: The object containing the set of nodes to hold.
        :param set autohold_key: A set with the tenant/project/job names
            associated with the given NodeSet.
        '''
        self.log.info("Holding nodeset %s" % (nodeset,))
        (hold_iterations,
         reason,
         node_hold_expiration) = self.sched.autohold_requests[autohold_key]
        nodes = nodeset.getNodes()

        for node in nodes:
            if node.lock is None:
                raise Exception("Node %s is not locked" % (node,))
            node.state = model.STATE_HOLD
            node.hold_job = " ".join(autohold_key)
            node.comment = reason
            if node_hold_expiration:
                node.hold_expiration = node_hold_expiration
            self.sched.zk.storeNode(node)

        # We remove the autohold when the number of nodes in hold
        # is equal to or greater than (run iteration count can be
        # altered) the number of nodes used in a single job run
        # times the number of run iterations requested.
        nodes_in_hold = self.sched.zk.heldNodeCount(autohold_key)
        if nodes_in_hold >= len(nodes) * hold_iterations:
            self.log.debug("Removing autohold for %s", autohold_key)
            del self.sched.autohold_requests[autohold_key]

    def useNodeSet(self, nodeset):
        self.log.info("Setting nodeset %s in use" % (nodeset,))
        for node in nodeset.getNodes():
            if node.lock is None:
                raise Exception("Node %s is not locked" % (node,))
            node.state = model.STATE_IN_USE
            self.sched.zk.storeNode(node)

    def returnNodeSet(self, nodeset, build=None):
        self.log.info("Returning nodeset %s" % (nodeset,))
        if (build and build.start_time and build.end_time and
            build.build_set and build.build_set.item and
            build.build_set.item.change and
            build.build_set.item.change.project):
            duration = build.end_time - build.start_time
            project = build.build_set.item.change.project
            self.log.info("Nodeset %s with %s nodes was in use "
                          "for %s seconds for build %s for project %s",
                          nodeset, len(nodeset.nodes), duration, build,
                          project)
        for node in nodeset.getNodes():
            if node.lock is None:
                self.log.error("Node %s is not locked" % (node,))
            else:
                try:
                    if node.state == model.STATE_IN_USE:
                        node.state = model.STATE_USED
                        self.sched.zk.storeNode(node)
                except Exception:
                    self.log.exception("Exception storing node %s "
                                       "while unlocking:" % (node,))
        self._unlockNodes(nodeset.getNodes())

    def unlockNodeSet(self, nodeset):
        self._unlockNodes(nodeset.getNodes())

    def _unlockNodes(self, nodes):
        for node in nodes:
            try:
                self.sched.zk.unlockNode(node)
            except Exception:
                self.log.exception("Error unlocking node:")

    def lockNodeSet(self, nodeset, request_id):
        self._lockNodes(nodeset.getNodes(), request_id)

    def _lockNodes(self, nodes, request_id):
        # Try to lock all of the supplied nodes.  If any lock fails,
        # try to unlock any which have already been locked before
        # re-raising the error.
        locked_nodes = []
        try:
            for node in nodes:
                if node.allocated_to != request_id:
                    raise Exception("Node %s allocated to %s, not %s" %
                                    (node.id, node.allocated_to, request_id))
                self.log.debug("Locking node %s" % (node,))
                self.sched.zk.lockNode(node, timeout=30)
                locked_nodes.append(node)
        except Exception:
            self.log.exception("Error locking nodes:")
            self._unlockNodes(locked_nodes)
            raise

    def _updateNodeRequest(self, request, deleted):
        # Return False to indicate that we should stop watching the
        # node.
        self.log.debug("Updating node request %s" % (request,))

        if request.uid not in self.requests:
            self.log.debug("Request %s is unknown" % (request.uid,))
            return False

        if request.canceled:
            del self.requests[request.uid]
            self.emitStats(request)
            return False

        # TODOv3(jeblair): handle allocation failure
        if deleted:
            self.log.debug("Resubmitting lost node request %s" % (request,))
            request.id = None
            self.sched.zk.submitNodeRequest(request, self._updateNodeRequest)
        elif request.state in (model.STATE_FULFILLED, model.STATE_FAILED):
            self.log.info("Node request %s %s" % (request, request.state))

            # Give our results to the scheduler.
            self.sched.onNodesProvisioned(request)
            del self.requests[request.uid]

            self.emitStats(request)

            # Stop watching this request node.
            return False

        return True

    def acceptNodes(self, request, request_id):
        # Called by the scheduler when it wants to accept and lock
        # nodes for (potential) use.  Return False if there is a
        # problem with the request (canceled or retrying), True if it
        # is ready to be acted upon (success or failure).

        self.log.info("Accepting node request %s" % (request,))

        if request_id != request.id:
            self.log.info("Skipping node accept for %s (resubmitted as %s)",
                          request_id, request.id)
            return False

        if request.canceled:
            self.log.info("Ignoring canceled node request %s" % (request,))
            # The request was already deleted when it was canceled
            return False

        # If we didn't request nodes and the request is fulfilled then just
        # return. We don't have to do anything in this case. Further don't even
        # ask ZK for the request as empty requests are not put into ZK.
        if not request.nodeset.nodes and request.fulfilled:
            return True

        # Make sure the request still exists. It's possible it could have
        # disappeared if we lost the ZK session between when the fulfillment
        # response was added to our queue, and when we actually get around to
        # processing it. Nodepool will automatically reallocate the assigned
        # nodes in that situation.
        try:
            if not self.sched.zk.nodeRequestExists(request):
                self.log.info("Request %s no longer exists, resubmitting",
                              request.id)
                request.id = None
                request.state = model.STATE_REQUESTED
                self.requests[request.uid] = request
                self.sched.zk.submitNodeRequest(
                    request, self._updateNodeRequest)
                return False
        except Exception:
            # If we cannot retrieve the node request from ZK we probably lost
            # the connection and thus the ZK session. Resubmitting the node
            # request probably doesn't make sense at this point in time as it
            # is likely to directly fail again. So just log the problem
            # with zookeeper and fail here.
            self.log.exception("Error getting node request %s:" % request_id)
            request.failed = True
            return True

        locked = False
        if request.fulfilled:
            # If the request suceeded, try to lock the nodes.
            try:
                self.lockNodeSet(request.nodeset, request.id)
                locked = True
            except Exception:
                self.log.exception("Error locking nodes:")
                request.failed = True

        # Regardless of whether locking (or even the request)
        # succeeded, delete the request.
        self.log.debug("Deleting node request %s" % (request,))
        try:
            self.sched.zk.deleteNodeRequest(request)
        except Exception:
            self.log.exception("Error deleting node request:")
            request.failed = True
            # If deleting the request failed, and we did lock the
            # nodes, unlock the nodes since we're not going to use
            # them.
            if locked:
                self.unlockNodeSet(request.nodeset)
        return True
