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
import re
import textwrap

from tests.base import AnsibleZuulTestCase


class TestZuulStream25(AnsibleZuulTestCase):
    tenant_config_file = 'config/remote-zuul-stream/main.yaml'
    ansible_version = '2.5'

    def setUp(self):
        super().setUp()
        self.fake_nodepool.remote_ansible = True

        ansible_remote = os.environ.get('ZUUL_REMOTE_IPV4')
        self.assertIsNotNone(ansible_remote)

    def _run_job(self, job_name):
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
                    - name: compute1
                      label: whatever
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
        return job

    def _get_job_output(self, build):
        path = os.path.join(self.test_root, build.uuid,
                            'work', 'logs', 'job-output.txt')
        with open(path) as f:
            return f.read()

    def assertLogLine(self, line, log):
        pattern = (r'^\d\d\d\d-\d\d-\d\d \d\d:\d\d\:\d\d\.\d\d\d\d\d\d \| %s$'
                   % line)
        log_re = re.compile(pattern, re.MULTILINE)
        m = log_re.search(log)
        if m is None:
            raise Exception("'%s' not found in log" % (line,))

    def test_command(self):
        job = self._run_job('command')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'SUCCESS')

            text = self._get_job_output(build)
            self.assertLogLine(
                r'RUN START: \[untrusted : review.example.com/org/project/'
                r'playbooks/command.yaml@master\]', text)
            self.assertLogLine(r'PLAY \[all\]', text)
            self.assertLogLine(
                r'Ansible version={}'.format(self.ansible_version), text)
            self.assertLogLine(r'TASK \[Show contents of first file\]', text)
            self.assertLogLine(r'controller \| command test one', text)
            self.assertLogLine(
                r'controller \| ok: Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine(r'TASK \[Show contents of second file\]', text)
            self.assertLogLine(r'compute1 \| command test two', text)
            self.assertLogLine(r'controller \| command test two', text)
            self.assertLogLine(r'compute1 \| This is a rescue task', text)
            self.assertLogLine(r'controller \| This is a rescue task', text)
            self.assertLogLine(r'compute1 \| This is an always task', text)
            self.assertLogLine(r'controller \| This is an always task', text)
            self.assertLogLine(r'compute1 \| This is a handler', text)
            self.assertLogLine(r'controller \| This is a handler', text)
            self.assertLogLine(r'controller \| First free task', text)
            self.assertLogLine(r'controller \| Second free task', text)
            self.assertLogLine(r'controller \| This is a shell task after an '
                               'included role', text)
            self.assertLogLine(r'compute1 \| This is a shell task after an '
                               'included role', text)
            self.assertLogLine(r'controller \| This is a command task after '
                               'an included role', text)
            self.assertLogLine(r'compute1 \| This is a command task after an '
                               'included role', text)
            self.assertLogLine(r'controller \| This is a shell task with '
                               'delegate compute1', text)
            self.assertLogLine(r'controller \| This is a shell task with '
                               'delegate controller', text)
            self.assertLogLine(r'compute1 \| item_in_loop1', text)
            self.assertLogLine(r'compute1 \| ok: Item: item_in_loop1 '
                               r'Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine(r'compute1 \| item_in_loop2', text)
            self.assertLogLine(r'compute1 \| ok: Item: item_in_loop2 '
                               r'Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine(r'compute1 \| failed_in_loop1', text)
            self.assertLogLine(r'compute1 \| ok: Item: failed_in_loop1 '
                               r'Result: 1', text)
            self.assertLogLine(r'compute1 \| failed_in_loop2', text)
            self.assertLogLine(r'compute1 \| ok: Item: failed_in_loop2 '
                               r'Result: 1', text)
            self.assertLogLine(r'localhost \| .*No such file or directory: .*'
                               r'\'/local-shelltask/somewhere/'
                               r'that/does/not/exist\'', text)
            self.assertLogLine(r'compute1 \| .*No such file or directory: .*'
                               r'\'/remote-shelltask/somewhere/'
                               r'that/does/not/exist\'', text)
            self.assertLogLine(r'controller \| .*No such file or directory: .*'
                               r'\'/remote-shelltask/somewhere/'
                               r'that/does/not/exist\'', text)
            self.assertLogLine(
                r'controller \| ok: Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine('PLAY RECAP', text)
            self.assertLogLine(
                r'controller \| ok: \d+ changed: \d+ unreachable: 0 failed: 1',
                text)
            self.assertLogLine(
                r'RUN END RESULT_NORMAL: \[untrusted : review.example.com/'
                r'org/project/playbooks/command.yaml@master]', text)

    def test_module_exception(self):
        job = self._run_job('module_failure_exception')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'FAILURE')

            text = self._get_job_output(build)
            self.assertLogLine(r'TASK \[Module failure\]', text)
            self.assertLogLine(
                r'controller \| MODULE FAILURE:', text)
            self.assertLogLine(
                r'controller \| Exception: This module is broken', text)

    def test_module_no_result(self):
        job = self._run_job('module_failure_no_result')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'FAILURE')

            text = self._get_job_output(build)
            self.assertLogLine(r'TASK \[Module failure\]', text)

            if self.ansible_version in ('2.5', '2.6'):
                regex = r'controller \| MODULE FAILURE: This module is broken'
            else:
                # Ansible starting with 2.7 emits a different error message
                # if a module exits without an exception or the ansible
                # supplied methods.
                regex = r'controller \|   "msg": "New-style module did not ' \
                        r'handle its own exit"'
            self.assertLogLine(regex, text)


class TestZuulStream26(TestZuulStream25):
    ansible_version = '2.6'


class TestZuulStream27(TestZuulStream25):
    ansible_version = '2.7'
