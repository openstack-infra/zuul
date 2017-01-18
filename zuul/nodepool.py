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


class Nodepool(object):
    log = logging.getLogger('zuul.nodepool')

    def __init__(self, scheduler):
        self.requests = {}
        self.sched = scheduler

    def requestNodes(self, build_set, job):
        # Create a copy of the nodeset to represent the actual nodes
        # returned by nodepool.
        nodeset = job.nodeset.copy()
        req = model.NodeRequest(build_set, job, nodeset)
        self.requests[req.uid] = req

        self.sched.zk.submitNodeRequest(req, self._updateNodeRequest)
        # Logged after submission so that we have the request id
        self.log.info("Submited node request %s" % (req,))

        return req

    def cancelRequest(self, request):
        self.log.info("Canceling node request %s" % (request,))
        if request.uid in self.requests:
            try:
                self.sched.zk.deleteNodeRequest(request)
            except Exception:
                self.log.exception("Error deleting node request:")
            del self.requests[request.uid]

    def useNodeset(self, nodeset):
        self.log.info("Setting nodeset %s in use" % (nodeset,))
        for node in nodeset.getNodes():
            if node.lock is None:
                raise Exception("Node %s is not locked" % (node,))
            node.state = model.STATE_IN_USE
            self.sched.zk.storeNode(node)

    def returnNodeset(self, nodeset):
        self.log.info("Returning nodeset %s" % (nodeset,))
        for node in nodeset.getNodes():
            if node.lock is None:
                raise Exception("Node %s is not locked" % (node,))
            if node.state == model.STATE_IN_USE:
                node.state = model.STATE_USED
                self.sched.zk.storeNode(node)
        self._unlockNodes(nodeset.getNodes())

    def unlockNodeset(self, nodeset):
        self._unlockNodes(nodeset.getNodes())

    def _unlockNodes(self, nodes):
        for node in nodes:
            try:
                self.sched.zk.unlockNode(node)
            except Exception:
                self.log.exception("Error unlocking node:")

    def lockNodeset(self, nodeset):
        self._lockNodes(nodeset.getNodes())

    def _lockNodes(self, nodes):
        # Try to lock all of the supplied nodes.  If any lock fails,
        # try to unlock any which have already been locked before
        # re-raising the error.
        locked_nodes = []
        try:
            for node in nodes:
                self.log.debug("Locking node %s" % (node,))
                self.sched.zk.lockNode(node)
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
            return False

        if request.state in (model.STATE_FULFILLED, model.STATE_FAILED):
            self.log.info("Node request %s %s" % (request, request.state))

            # Give our results to the scheduler.
            self.sched.onNodesProvisioned(request)
            del self.requests[request.uid]

            # Stop watching this request node.
            return False
        # TODOv3(jeblair): handle allocation failure
        elif deleted:
            self.log.debug("Resubmitting lost node request %s" % (request,))
            self.sched.zk.submitNodeRequest(request, self._updateNodeRequest)
        return True

    def acceptNodes(self, request):
        # Called by the scheduler when it wants to accept and lock
        # nodes for (potential) use.

        self.log.info("Accepting node request %s" % (request,))

        locked = False
        if request.fulfilled:
            # If the request suceeded, try to lock the nodes.
            try:
                self.lockNodeset(request.nodeset)
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
                self.unlockNodeset(request.nodeset)
