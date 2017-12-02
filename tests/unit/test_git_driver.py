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


import os
import time
import yaml

from tests.base import ZuulTestCase, simple_layout


class TestGitDriver(ZuulTestCase):
    config_file = 'zuul-git-driver.conf'
    tenant_config_file = 'config/git-driver/main.yaml'

    def setup_config(self):
        super(TestGitDriver, self).setup_config()
        self.config.set('connection git', 'baseurl', self.upstream_root)

    def test_basic(self):
        tenant = self.sched.abide.tenants.get('tenant-one')
        # Check that we have the git source for common-config and the
        # gerrit source for the project.
        self.assertEqual('git', tenant.config_projects[0].source.name)
        self.assertEqual('common-config', tenant.config_projects[0].name)
        self.assertEqual('gerrit', tenant.untrusted_projects[0].source.name)
        self.assertEqual('org/project', tenant.untrusted_projects[0].name)

        # The configuration for this test is accessed via the git
        # driver (in common-config), rather than the gerrit driver, so
        # if the job runs, it worked.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(A.reported, 1)

    def test_config_refreshed(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(A.reported, 1)
        self.assertEqual(self.history[0].name, 'project-test1')

        # Update zuul.yaml to force a tenant reconfiguration
        path = os.path.join(self.upstream_root, 'common-config', 'zuul.yaml')
        config = yaml.load(open(path, 'r').read())
        change = {
            'name': 'org/project',
            'check': {
                'jobs': [
                    'project-test2'
                ]
            }
        }
        config[4]['project'] = change
        files = {'zuul.yaml': yaml.dump(config)}
        self.addCommitToRepo(
            'common-config', 'Change zuul.yaml configuration', files)

        # Let some time for the tenant reconfiguration to happen
        time.sleep(2)
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(A.reported, 1)
        # We make sure the new job has run
        self.assertEqual(self.history[1].name, 'project-test2')

        # Let's stop the git Watcher to let us merge some changes commits
        # We want to verify that config changes are detected for commits
        # on the range oldrev..newrev
        self.sched.connections.getSource('git').connection.w_pause = True
        # Add a config change
        change = {
            'name': 'org/project',
            'check': {
                'jobs': [
                    'project-test1'
                ]
            }
        }
        config[4]['project'] = change
        files = {'zuul.yaml': yaml.dump(config)}
        self.addCommitToRepo(
            'common-config', 'Change zuul.yaml configuration', files)
        # Add two other changes
        self.addCommitToRepo(
            'common-config', 'Adding f1',
            {'f1': "Content"})
        self.addCommitToRepo(
            'common-config', 'Adding f2',
            {'f2': "Content"})
        # Restart the git watcher
        self.sched.connections.getSource('git').connection.w_pause = False

        # Let some time for the tenant reconfiguration to happen
        time.sleep(2)
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 3)
        self.assertEqual(A.reported, 1)
        # We make sure the new job has run
        self.assertEqual(self.history[2].name, 'project-test1')

    def ensure_watcher_has_context(self):
        # Make sure watcher have read initial refs shas
        cnx = self.sched.connections.getSource('git').connection
        delay = 0.1
        max_delay = 1
        while not cnx.projects_refs:
            time.sleep(delay)
            max_delay -= delay
            if max_delay <= 0:
                raise Exception("Timeout waiting for initial read")

    @simple_layout('layouts/basic-git.yaml', driver='git')
    def test_ref_updated_event(self):
        self.ensure_watcher_has_context()
        # Add a commit to trigger a ref-updated event
        self.addCommitToRepo(
            'org/project', 'A change for ref-updated', {'f1': 'Content'})
        # Let some time for the git watcher to detect the ref-update event
        time.sleep(0.2)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('post-job').result)

    @simple_layout('layouts/basic-git.yaml', driver='git')
    def test_ref_created(self):
        self.ensure_watcher_has_context()
        # Tag HEAD to trigger a ref-updated event
        self.addTagToRepo(
            'org/project', 'atag', 'HEAD')
        # Let some time for the git watcher to detect the ref-update event
        time.sleep(0.2)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('tag-job').result)

    @simple_layout('layouts/basic-git.yaml', driver='git')
    def test_ref_deleted(self):
        self.ensure_watcher_has_context()
        # Delete default tag init to trigger a ref-updated event
        self.delTagFromRepo(
            'org/project', 'init')
        # Let some time for the git watcher to detect the ref-update event
        time.sleep(0.2)
        self.waitUntilSettled()
        # Make sure no job as run as ignore-delete is True by default
        self.assertEqual(len(self.history), 0)
