# Copyright 2016 Red Hat, Inc.
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


class TestGitDriver(ZuulTestCase):
    config_file = 'zuul-git-driver.conf'
    tenant_config_file = 'config/git-driver/main.yaml'

    def setup_config(self):
        super(TestGitDriver, self).setup_config()
        self.config.set('connection git', 'baseurl', self.upstream_root)

    def test_git_driver(self):
        tenant = self.sched.abide.tenants.get('tenant-one')
        # Check that we have the git source for common-config and the
        # gerrit source for the project.
        self.assertEqual('git', tenant.config_repos[0].source.name)
        self.assertEqual('common-config', tenant.config_repos[0].name)
        self.assertEqual('gerrit', tenant.project_repos[0].source.name)
        self.assertEqual('org/project', tenant.project_repos[0].name)

        # The configuration for this test is accessed via the git
        # driver (in common-config), rather than the gerrit driver, so
        # if the job runs, it worked.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(A.reported, 1)
