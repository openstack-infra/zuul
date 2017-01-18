# Copyright 2015 Red Hat, Inc.
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


import time

import zuul.zk
import zuul.nodepool
from zuul import model

from tests.base import BaseTestCase, ChrootedKazooFixture, FakeNodepool


class TestNodepool(BaseTestCase):
    # Tests the Nodepool interface class using a fake nodepool and
    # scheduler.

    def setUp(self):
        super(BaseTestCase, self).setUp()

        self.zk_chroot_fixture = self.useFixture(ChrootedKazooFixture())
        self.zk_config = zuul.zk.ZooKeeperConnectionConfig(
            self.zk_chroot_fixture.zookeeper_host,
            self.zk_chroot_fixture.zookeeper_port,
            self.zk_chroot_fixture.zookeeper_chroot)

        self.zk = zuul.zk.ZooKeeper()
        self.zk.connect([self.zk_config])

        self.provisioned_requests = []
        # This class implements the scheduler methods zuul.nodepool
        # needs, so we pass 'self' as the scheduler.
        self.nodepool = zuul.nodepool.Nodepool(self)

        self.fake_nodepool = FakeNodepool(self.zk_config.host,
                                          self.zk_config.port,
                                          self.zk_config.chroot)

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
        nodeset.addNode(model.Node('controller', 'ubuntu-xenial'))
        nodeset.addNode(model.Node('compute', 'ubuntu-xenial'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        request = self.nodepool.requestNodes(None, job)
        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 1)
        self.assertEqual(request.state, 'fulfilled')

    def test_node_request_disconnect(self):
        # Test that node requests are re-submitted after disconnect

        nodeset = model.NodeSet()
        nodeset.addNode(model.Node('controller', 'ubuntu-xenial'))
        nodeset.addNode(model.Node('compute', 'ubuntu-xenial'))
        job = model.Job('testjob')
        job.nodeset = nodeset
        self.fake_nodepool.paused = True
        request = self.nodepool.requestNodes(None, job)
        self.zk.client.stop()
        self.zk.client.start()
        self.fake_nodepool.paused = False
        self.waitForRequests()
        self.assertEqual(len(self.provisioned_requests), 1)
        self.assertEqual(request.state, 'fulfilled')
