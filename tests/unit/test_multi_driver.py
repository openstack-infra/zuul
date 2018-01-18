# Copyright 2015 GoodData
# Copyright (c) 2017 IBM Corp.
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


class TestGerritAndGithub(ZuulTestCase):
    config_file = 'zuul-connections-gerrit-and-github.conf'
    tenant_config_file = 'config/multi-driver/main.yaml'

    def setup_config(self):
        super(TestGerritAndGithub, self).setup_config()

    def test_multiple_project_gerrit_and_github(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        B = self.fake_github.openFakePullRequest('org/project1', 'master', 'B')
        self.fake_github.emitEvent(B.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        self.assertEqual(2, len(self.builds))
        self.assertEqual('project-gerrit', self.builds[0].name)
        self.assertEqual('project1-github', self.builds[1].name)
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertTrue(self.builds[1].hasChanges(B))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        # Check on reporting results
        # github should have a success status (only).
        statuses = self.fake_github.getCommitStatuses(
            'org/project1', B.head_sha)
        self.assertEqual(1, len(statuses))
        self.assertEqual('success', statuses[0]['state'])

        # gerrit should have only reported twice, on start and success
        self.assertEqual(A.reported, 2)
