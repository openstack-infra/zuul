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


class TestZuulStream(AnsibleZuulTestCase):
    tenant_config_file = 'config/remote-zuul-stream/main.yaml'

    def setUp(self):
        super(TestZuulStream, self).setUp()
        self.fake_nodepool.remote_ansible = True

        ansible_remote = os.environ.get('ZUUL_REMOTE_IPV4')
        self.assertIsNotNone(ansible_remote)

        # on some systems this test may run longer than 30 seconds
        self.wait_timeout = 60

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
            """.format(job_name=job_name))

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
        pattern = ('^\d\d\d\d-\d\d-\d\d \d\d:\d\d\:\d\d\.\d\d\d\d\d\d \| %s$' %
                   line)
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
                'RUN START: \[untrusted : review.example.com/org/project/'
                'playbooks/command.yaml@master\]', text)
            self.assertLogLine('PLAY \[all\]', text)
            self.assertLogLine('TASK \[Show contents of first file\]', text)
            self.assertLogLine('controller \| command test one', text)
            self.assertLogLine(
                'controller \| ok: Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine('TASK \[Show contents of second file\]', text)
            self.assertLogLine('compute1 \| command test two', text)
            self.assertLogLine('controller \| command test two', text)
            self.assertLogLine('compute1 \| This is a rescue task', text)
            self.assertLogLine('controller \| This is a rescue task', text)
            self.assertLogLine('compute1 \| This is an always task', text)
            self.assertLogLine('controller \| This is an always task', text)
            self.assertLogLine('compute1 \| This is a handler', text)
            self.assertLogLine('controller \| This is a handler', text)
            self.assertLogLine('controller \| First free task', text)
            self.assertLogLine('controller \| Second free task', text)
            self.assertLogLine('controller \| This is a shell task after an '
                               'included role', text)
            self.assertLogLine('compute1 \| This is a shell task after an '
                               'included role', text)
            self.assertLogLine('controller \| This is a command task after an '
                               'included role', text)
            self.assertLogLine('compute1 \| This is a command task after an '
                               'included role', text)
            self.assertLogLine('controller \| This is a shell task with '
                               'delegate compute1', text)
            self.assertLogLine('controller \| This is a shell task with '
                               'delegate controller', text)
            self.assertLogLine(
                'controller \| ok: Runtime: \d:\d\d:\d\d\.\d\d\d\d\d\d', text)
            self.assertLogLine('PLAY RECAP', text)
            self.assertLogLine(
                'controller \| ok: \d+ changed: \d+ unreachable: 0 failed: 1',
                text)
            self.assertLogLine(
                'RUN END RESULT_NORMAL: \[untrusted : review.example.com/'
                'org/project/playbooks/command.yaml@master]', text)

    def test_module_failure(self):
        job = self._run_job('module_failure')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'FAILURE')

            text = self._get_job_output(build)
            self.assertLogLine('TASK \[Module failure\]', text)
            self.assertLogLine(
                'controller \| MODULE FAILURE: This module is broken', text)
