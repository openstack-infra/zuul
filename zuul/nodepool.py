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

from zuul.model import NodeRequest


class Nodepool(object):
    log = logging.getLogger('zuul.nodepool')

    def __init__(self, scheduler):
        self.requests = {}
        self.sched = scheduler

    def requestNodes(self, build_set, job):
        # Create a copy of the nodeset to represent the actual nodes
        # returned by nodepool.
        nodeset = job.nodeset.copy()
        req = NodeRequest(build_set, job, nodeset)
        self.requests[req.uid] = req
        self.log.debug("Submitting node request: %s" % (req,))

        self.sched.zk.submitNodeRequest(req, self._updateNodeRequest)

        return req

    def cancelRequest(self, request):
        if request in self.requests:
            self.requests.remove(request)

    def returnNodes(self, nodes, used=True):
        pass

    def _updateNodeRequest(self, request, deleted):
        # Return False to indicate that we should stop watching the
        # node.
        self.log.debug("Updating node request: %s" % (request,))

        if request.uid not in self.requests:
            return False

        if request.state == 'fulfilled':
            self.sched.onNodesProvisioned(request)
            del self.requests[request.uid]
            return False
        elif deleted:
            self.log.debug("Resubmitting lost node request %s" % (request,))
            self.sched.zk.submitNodeRequest(request, self._updateNodeRequest)
        return True
