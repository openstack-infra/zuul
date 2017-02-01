#!/usr/bin/env python

# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

from tests.base import AnsibleZuulTestCase


class TestOpenStack(AnsibleZuulTestCase):
    # A temporary class to experiment with how openstack can use
    # Zuulv3

    tenant_config_file = 'config/openstack/main.yaml'

    def test_nova_master(self):
        A = self.fake_gerrit.addFakeChange('openstack/nova', 'master', 'A')
        A.addApproval('code-review', 2)
        self.fake_gerrit.addEvent(A.addApproval('approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('python27').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('python35').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertEqual(self.getJobFromHistory('python27').node,
                         'ubuntu-xenial')

    def test_nova_mitaka(self):
        self.create_branch('openstack/nova', 'stable/mitaka')
        A = self.fake_gerrit.addFakeChange('openstack/nova',
                                           'stable/mitaka', 'A')
        A.addApproval('code-review', 2)
        self.fake_gerrit.addEvent(A.addApproval('approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('python27').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('python35').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertEqual(self.getJobFromHistory('python27').node,
                         'ubuntu-trusty')
