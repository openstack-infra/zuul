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


class TestPushRequirements(ZuulTestCase):
    config_file = 'zuul-push-reqs.conf'
    tenant_config_file = 'config/push-reqs/main.yaml'

    def setup_config(self):
        super(TestPushRequirements, self).setup_config()

    def test_push_requirements(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest('org/project1', 'master', 'A')
        new_sha = A.head_sha
        A.setMerged("merging A")
        pevent = self.fake_github.getPushEvent(project='org/project1',
                                               ref='refs/heads/master',
                                               new_rev=new_sha)

        self.fake_github.emitEvent(pevent)

        self.waitUntilSettled()

        # All but one pipeline should be skipped
        self.assertEqual(1, len(self.builds))
        self.assertEqual('pushhub', self.builds[0].pipeline)
        self.assertEqual('org/project1', self.builds[0].project)

        # Make a gerrit change, and emit a ref-updated event
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        self.fake_gerrit.addEvent(B.getRefUpdatedEvent())
        B.setMerged()
        self.waitUntilSettled()

        # All but one pipeline should be skipped, increasing builds by 1
        self.assertEqual(2, len(self.builds))
        self.assertEqual('pushgerrit', self.builds[1].pipeline)
        self.assertEqual('org/project2', self.builds[1].project)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
