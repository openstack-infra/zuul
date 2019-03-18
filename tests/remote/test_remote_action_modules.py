# Copyright 2018 Red Hat, Inc.
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
import textwrap

from tests.base import AnsibleZuulTestCase, FIXTURE_DIR

ERROR_ACCESS_OUTSIDE = "Accessing files from outside the working dir"
ERROR_SYNC_TO_OUTSIDE = "Syncing files to outside the working dir"
ERROR_SYNC_FROM_OUTSIDE = "Syncing files from outside the working dir"


class TestActionModules25(AnsibleZuulTestCase):
    tenant_config_file = 'config/remote-action-modules/main.yaml'
    ansible_version = '2.5'

    def setUp(self):
        super().setUp()
        self.fake_nodepool.remote_ansible = True

        ansible_remote = os.environ.get('ZUUL_REMOTE_IPV4')
        self.assertIsNotNone(ansible_remote)

        # inject some files as forbidden sources
        fixture_dir = os.path.join(FIXTURE_DIR, 'bwrap-mounts')
        self.executor_server.execution_wrapper.bwrap_command.extend(
            ['--ro-bind', fixture_dir, '/opt'])

    def _run_job(self, job_name, result, expect_error=None):
        # Keep the jobdir around so we can inspect contents if an
        # assert fails. It will be cleaned up anyway as it is contained
        # in a tmp dir which gets cleaned up after the test.
        self.executor_server.keep_jobdir = True

        # Output extra ansible info so we might see errors.
        self.executor_server.verbose = True
        conf = textwrap.dedent(
            """
            - job:
                name: {job_name}
                run: playbooks/{job_name}.yaml
                ansible-version: {version}
                roles:
                  - zuul: org/common-config
                nodeset:
                  nodes:
                    - name: controller
                      label: whatever

            - project:
                check:
                  jobs:
                    - {job_name}
            """.format(job_name=job_name, version=self.ansible_version))

        file_dict = {'zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        job = self.getJobFromHistory(job_name)
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, result)

            if expect_error:
                path = os.path.join(self.test_root, build.uuid,
                                    'work', 'logs', 'job-output.txt')
                with open(path, 'r') as f:
                    self.assertIn(expect_error, f.read())

    def test_assemble_module(self):
        self._run_job('assemble-good', 'SUCCESS')

        # assemble-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('assemble-delegate', 'SUCCESS')
        self._run_job('assemble-localhost', 'SUCCESS')

        self._run_job('assemble-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('assemble-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('assemble-bad-dir-with-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)

    def test_command_module(self):
        self._run_job('command-good', 'SUCCESS')

    def test_zuul_return_module(self):
        self._run_job('zuul_return-good', 'SUCCESS')

    def test_zuul_return_module_delegate_to(self):
        self._run_job('zuul_return-good-delegate', 'SUCCESS')

    def test_copy_module(self):
        self._run_job('copy-good', 'SUCCESS')

        # copy-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('copy-delegate', 'SUCCESS')
        self._run_job('copy-localhost', 'SUCCESS')

        self._run_job('copy-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('copy-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('copy-bad-dir-with-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)

    def test_includevars_module(self):
        self._run_job('includevars-good', 'SUCCESS')
        self._run_job('includevars-good-dir', 'SUCCESS')

        self._run_job('includevars-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('includevars-bad-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)
        self._run_job('includevars-bad-dir', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('includevars-bad-dir-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)
        self._run_job('includevars-bad-dir-with-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)
        self._run_job('includevars-bad-dir-with-double-symlink', 'FAILURE',
                      ERROR_ACCESS_OUTSIDE)

    def test_patch_module(self):
        self._run_job('patch-good', 'SUCCESS')

        # patch-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('patch-delegate', 'SUCCESS')
        self._run_job('patch-localhost', 'SUCCESS')

        self._run_job('patch-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('patch-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)

    def test_raw_module(self):
        self._run_job('raw-good', 'SUCCESS')

        # raw-delegate does multiple tests with various delegates. It
        # asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('raw-delegate', 'SUCCESS')
        self._run_job('raw-localhost', 'SUCCESS')

    def test_script_module(self):
        self._run_job('script-good', 'SUCCESS')

        # script-delegate does multiple tests with various delegates. It
        # asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('script-delegate', 'SUCCESS')
        self._run_job('script-localhost', 'SUCCESS')

        self._run_job('script-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('script-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)

    def test_shell_module(self):
        self._run_job('shell-good', 'SUCCESS')

    def test_synchronize_module(self):
        self._run_job('synchronize-good', 'SUCCESS')
        self._run_job('synchronize-bad-pull', 'FAILURE', ERROR_SYNC_TO_OUTSIDE)
        self._run_job(
            'synchronize-bad-push', 'FAILURE', ERROR_SYNC_FROM_OUTSIDE)
        self._run_job('synchronize-delegate-good', 'SUCCESS')

    def test_template_module(self):
        self._run_job('template-good', 'SUCCESS')

        # template-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('template-delegate', 'SUCCESS')
        self._run_job('template-localhost', 'SUCCESS')

        self._run_job('template-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('template-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)

    def test_unarchive_module(self):
        self._run_job('unarchive-good', 'SUCCESS')

        # template-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('unarchive-delegate', 'SUCCESS')
        self._run_job('unarchive-localhost', 'SUCCESS')

        self._run_job('unarchive-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)
        self._run_job('unarchive-bad-symlink', 'FAILURE', ERROR_ACCESS_OUTSIDE)

    def test_known_hosts_module(self):
        self._run_job('known-hosts-good', 'SUCCESS')

        # known-hosts-delegate does multiple tests with various delegates and
        # safe and non-safe paths. It asserts by itself within ansible so we
        # expect SUCCESS here.
        self._run_job('known-hosts-delegate', 'SUCCESS')
        self._run_job('known-hosts-localhost', 'SUCCESS')

        self._run_job('known-hosts-bad', 'FAILURE', ERROR_ACCESS_OUTSIDE)


class TestActionModules26(TestActionModules25):
    ansible_version = '2.6'


class TestActionModules27(TestActionModules25):
    ansible_version = '2.7'
