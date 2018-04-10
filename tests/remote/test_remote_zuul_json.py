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

import dateutil
import json
import os
import textwrap

from tests.base import AnsibleZuulTestCase


class TestZuulJSON(AnsibleZuulTestCase):
    tenant_config_file = 'config/remote-zuul-json/main.yaml'

    def setUp(self):
        super(TestZuulJSON, self).setUp()
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
            """.format(job_name=job_name))

        file_dict = {'zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        job = self.getJobFromHistory(job_name)
        return job

    def _get_json_as_text(self, build):
        path = os.path.join(self.test_root, build.uuid,
                            'work', 'logs', 'job-output.json')
        with open(path) as f:
            return f.read()

    def test_no_log(self):
        job = self._run_job('no-log')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'SUCCESS')

            text = self._get_json_as_text(build)
            self.assertIn('rosebud', text)
            self.assertNotIn('setec', text)

    def test_json_role_log(self):
        job = self._run_job('json-role')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'SUCCESS')

            text = self._get_json_as_text(build)
            self.assertIn('json-role', text)

            json_result = json.loads(text)
            role_name = json_result[0]['plays'][0]['tasks'][0]['role']['name']
            self.assertEqual('json-role', role_name)

    def test_json_time_log(self):
        job = self._run_job('no-log')
        with self.jobLog(job):
            build = self.history[-1]
            self.assertEqual(build.result, 'SUCCESS')

            text = self._get_json_as_text(build)
            # Assert that 'start' and 'end' are part of the result at all
            self.assertIn('start', text)
            self.assertIn('end', text)

            json_result = json.loads(text)
            # Assert that the start and end timestamps are present at the
            # right place in the dictionary
            task = json_result[0]['plays'][0]['tasks'][0]['task']
            task_start_time = task['duration']['start']
            task_end_time = task['duration']['end']

            play = json_result[0]['plays'][0]['play']
            play_start_time = play['duration']['start']
            play_end_time = play['duration']['end']

            # Assert that the start and end timestamps are valid dates
            dateutil.parser.parse(task_start_time)
            dateutil.parser.parse(task_end_time)
            dateutil.parser.parse(play_start_time)
            dateutil.parser.parse(play_end_time)
