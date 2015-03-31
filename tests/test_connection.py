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

import logging
import testtools

import zuul.connection.gerrit

from tests.base import ZuulTestCase


class TestGerritConnection(testtools.TestCase):
    log = logging.getLogger("zuul.test_connection")

    def test_driver_name(self):
        self.assertEqual('gerrit',
                         zuul.connection.gerrit.GerritConnection.driver_name)


class TestConnections(ZuulTestCase):
    def setup_config(self, config_file='zuul-connections-same-gerrit.conf'):
        super(TestConnections, self).setup_config(config_file)

    def test_multiple_connections(self):
        "Test multiple connections to the one gerrit"

        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_review_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(A.patchsets[-1]['approvals']), 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['type'], 'VRFY')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '1')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['by']['username'],
                         'jenkins')

        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.worker.addFailTest('project-test2', B)
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(B.patchsets[-1]['approvals']), 1)
        self.assertEqual(B.patchsets[-1]['approvals'][0]['type'], 'VRFY')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['by']['username'],
                         'civoter')


class TestMultipleGerrits(ZuulTestCase):
    def setup_config(self,
                     config_file='zuul-connections-multiple-gerrits.conf'):
        super(TestMultipleGerrits, self).setup_config(config_file)
        self.config.set(
            'zuul', 'layout_config',
            'layout-connections-multiple-gerrits.yaml')

    def test_multiple_project_separate_gerrits(self):
        self.worker.hold_jobs_in_build = True

        A = self.fake_another_gerrit.addFakeChange(
            'org/project', 'master', 'A')
        self.fake_another_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(1, len(self.builds))
        self.assertEqual('project-another-gerrit', self.builds[0].name)
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
