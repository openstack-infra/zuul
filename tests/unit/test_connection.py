# Copyright 2014 Rackspace Australia
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

from tests.base import ZuulTestCase


class TestConnections(ZuulTestCase):
    config_file = 'zuul-connections-same-gerrit.conf'
    tenant_config_file = 'config/zuul-connections-same-gerrit/main.yaml'

    def test_multiple_connections(self):
        "Test multiple connections to the one gerrit"

        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.addEvent('review_gerrit', A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(A.patchsets[-1]['approvals']), 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['type'], 'verified')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '1')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['by']['username'],
                         'jenkins')

        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.launch_server.failJob('project-test2', B)
        self.addEvent('review_gerrit', B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(B.patchsets[-1]['approvals']), 1)
        self.assertEqual(B.patchsets[-1]['approvals'][0]['type'], 'verified')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['by']['username'],
                         'civoter')


class TestMultipleGerrits(ZuulTestCase):

    config_file = 'zuul-connections-multiple-gerrits.conf'
    tenant_config_file = 'config/zuul-connections-multiple-gerrits/main.yaml'

    def test_multiple_project_separate_gerrits(self):
        self.launch_server.hold_jobs_in_build = True

        A = self.fake_another_gerrit.addFakeChange(
            'org/project1', 'master', 'A')
        self.fake_another_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([dict(name='project-test2',
                                changes='1,1',
                                project='org/project1',
                                pipeline='another_check')])

        # NOTE(jamielennox): the tests back the git repo for both connections
        # onto the same git repo on the file system. If we just create another
        # fake change the fake_review_gerrit will try to create another 1,1
        # change and git will fail to create the ref. Arbitrarily set it to get
        # around the problem.
        self.fake_review_gerrit.change_number = 50

        B = self.fake_review_gerrit.addFakeChange(
            'org/project1', 'master', 'B')
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='project-test2',
                 changes='1,1',
                 project='org/project1',
                 pipeline='another_check'),
            dict(name='project-test1',
                 changes='51,1',
                 project='org/project1',
                 pipeline='review_check'),
        ])

        self.launch_server.hold_jobs_in_build = False
        self.launch_server.release()
        self.waitUntilSettled()
