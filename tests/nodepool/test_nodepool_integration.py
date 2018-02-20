# Copyright 2017 Red Hat, Inc.
#
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

import socket
import time
from unittest import skip

import zuul.zk
import zuul.nodepool
from zuul import model

from tests.base import BaseTestCase


class TestNodepoolIntegration(BaseTestCase):
    # Tests the Nodepool interface class using a *real* nodepool and
    # fake scheduler.

    def setUp(self):
        super(TestNodepoolIntegration, self).setUp()

        self.statsd = None
        self.zk = zuul.zk.ZooKeeper()
        self.addCleanup(self.zk.disconnect)
        self.zk.connect('localhost:2181')
        self.hostname = socket.gethostname()

        self.provisioned_requests = []
        # This class implements the scheduler methods zuul.nodepool
        # needs, so we pass 'self' as the scheduler.
        self.nodepool = zuul.nodepool.Nodepool(self)

    def waitForRequests(self):
        # Wait until all requests are complete.
        while self.nodepool.requests:
            time.sleep(0.1)

    def onNodesProvisioned(self, request):
        # This is a scheduler method that the nodepool class calls
        # back when a request is provisioned.
        self.provisioned_requests.append(request)

    def test_node_request(self):
        # Test a simple node request

        nodeset = model.NodeSet()
        nodeset.addNode(model.Node(['controller'], 'fake-label'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        request = self.nodepool.requestNodes(None, job)
        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 1)
        self.assertEqual(request.state, model.STATE_FULFILLED)

        # Accept the nodes
        self.nodepool.acceptNodes(request, request.id)
        nodeset = request.nodeset

        for node in nodeset.getNodes():
            self.assertIsNotNone(node.lock)
            self.assertEqual(node.state, model.STATE_READY)

        # Mark the nodes in use
        self.nodepool.useNodeSet(nodeset)
        for node in nodeset.getNodes():
            self.assertEqual(node.state, model.STATE_IN_USE)

        # Return the nodes
        self.nodepool.returnNodeSet(nodeset)
        for node in nodeset.getNodes():
            self.assertIsNone(node.lock)
            self.assertEqual(node.state, model.STATE_USED)

    def test_invalid_node_request(self):
        # Test requests with an invalid node type fail
        nodeset = model.NodeSet()
        nodeset.addNode(model.Node(['controller'], 'invalid-label'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        request = self.nodepool.requestNodes(None, job)
        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 1)
        self.assertEqual(request.state, model.STATE_FAILED)

    @skip("Disabled until nodepool is ready")
    def test_node_request_disconnect(self):
        # Test that node requests are re-submitted after disconnect

        nodeset = model.NodeSet()
        nodeset.addNode(model.Node(['controller'], 'ubuntu-xenial'))
        nodeset.addNode(model.Node(['compute'], 'ubuntu-xenial'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        self.fake_nodepool.paused = True
        request = self.nodepool.requestNodes(None, job)
        self.zk.client.stop()
        self.zk.client.start()
        self.fake_nodepool.paused = False
        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 1)
        self.assertEqual(request.state, model.STATE_FULFILLED)

    @skip("Disabled until nodepool is ready")
    def test_node_request_canceled(self):
        # Test that node requests can be canceled

        nodeset = model.NodeSet()
        nodeset.addNode(model.Node(['controller'], 'ubuntu-xenial'))
        nodeset.addNode(model.Node(['compute'], 'ubuntu-xenial'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        self.fake_nodepool.paused = True
        request = self.nodepool.requestNodes(None, job)
        self.nodepool.cancelRequest(request)

        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 0)
