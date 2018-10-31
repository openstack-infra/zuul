# Copyright 2015 BMW Car IT GmbH
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
from unittest import mock

import tests.base
from tests.base import BaseTestCase, ZuulTestCase, AnsibleZuulTestCase
from zuul.driver.gerrit import GerritDriver
from zuul.driver.gerrit.gerritconnection import GerritConnection

FIXTURE_DIR = os.path.join(tests.base.FIXTURE_DIR, 'gerrit')


def read_fixture(file):
    with open('%s/%s' % (FIXTURE_DIR, file), 'r') as fixturefile:
        lines = fixturefile.readlines()
        command = lines[0].replace('\n', '')
        value = ''.join(lines[1:])
        return command, value


def read_fixtures(files):
    calls = []
    values = []
    for fixture_file in files:
        command, value = read_fixture(fixture_file)
        calls.append(mock.call(command))
        values.append([value, ''])
    return calls, values


class TestGerrit(BaseTestCase):

    @mock.patch('zuul.driver.gerrit.gerritconnection.GerritConnection._ssh')
    def run_query(self, files, expected_patches, _ssh_mock):
        gerrit_config = {
            'user': 'gerrit',
            'server': 'localhost',
        }
        driver = GerritDriver()
        gerrit = GerritConnection(driver, 'review_gerrit', gerrit_config)

        calls, values = read_fixtures(files)
        _ssh_mock.side_effect = values

        result = gerrit.simpleQuery('project:openstack-infra/zuul')

        _ssh_mock.assert_has_calls(calls)
        self.assertEqual(len(calls), _ssh_mock.call_count,
                         '_ssh should be called %d times' % len(calls))
        self.assertIsNotNone(result, 'Result is not none')
        self.assertEqual(len(result), expected_patches,
                         'There must be %d patches.' % expected_patches)

    def test_simple_query_pagination_new(self):
        files = ['simple_query_pagination_new_1',
                 'simple_query_pagination_new_2']
        expected_patches = 5
        self.run_query(files, expected_patches)

    def test_simple_query_pagination_old(self):
        files = ['simple_query_pagination_old_1',
                 'simple_query_pagination_old_2',
                 'simple_query_pagination_old_3']
        expected_patches = 5
        self.run_query(files, expected_patches)

    def test_ref_name_check_rules(self):
        # See man git-check-ref-format for the rules referenced here
        test_strings = [
            ('refs/heads/normal', True),
            ('refs/heads/.bad', False),  # rule 1
            ('refs/heads/bad.lock', False),  # rule 1
            ('refs/heads/good.locked', True),
            ('refs/heads/go.od', True),
            ('refs/heads//bad', False),  # rule 6
            ('refs/heads/b?d', False),  # rule 5
            ('refs/heads/b[d', False),  # rule 5
            ('refs/heads/b..ad', False),  # rule 3
            ('bad', False),  # rule 2
            ('refs/heads/\nbad', False),  # rule 4
            ('/refs/heads/bad', False),  # rule 6
            ('refs/heads/bad/', False),  # rule 6
            ('refs/heads/bad.', False),  # rule 7
            ('.refs/heads/bad', False),  # rule 1
            ('refs/he@{ads/bad', False),  # rule 8
            ('@', False),  # rule 9
            ('refs\\heads/bad', False)  # rule 10
        ]

        for ref, accepted in test_strings:
            self.assertEqual(
                accepted,
                GerritConnection._checkRefFormat(ref),
                ref + ' shall be ' + ('accepted' if accepted else 'rejected'))


class TestGerritWeb(ZuulTestCase):
    config_file = 'zuul-gerrit-web.conf'
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_jobs_executed(self):
        "Test that jobs are executed and a change is merged"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(self.getJobFromHistory('project-test1').node,
                         'label1')
        self.assertEqual(self.getJobFromHistory('project-test2').node,
                         'label1')

    def test_dynamic_line_comment(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: garbage-job
                garbage: True
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('Zuul encountered a syntax error',
                      A.messages[0])
        comments = sorted(A.comments, key=lambda x: x['line'])
        self.assertEqual(comments[0],
                         {'file': '.zuul.yaml',
                          'line': 4,
                          'message': "extra keys not allowed @ "
                                     "data['garbage']",
                          'range': {'end_character': 0,
                                    'end_line': 4,
                                    'start_character': 2,
                                    'start_line': 2},
                          'reviewer': {'email': 'zuul@example.com',
                                       'name': 'Zuul',
                                       'username': 'jenkins'}}
        )

    def test_dependent_dynamic_line_comment(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: garbage-job
                garbage: True
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(B.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('Zuul encountered a syntax error',
                      B.messages[0])
        self.assertEqual(B.comments, [])


class TestFileComments(AnsibleZuulTestCase):
    config_file = 'zuul-gerrit-web.conf'
    tenant_config_file = 'config/gerrit-file-comments/main.yaml'

    def test_file_comments(self):
        A = self.fake_gerrit.addFakeChange(
            'org/project', 'master', 'A',
            files={'path/to/file.py': 'test1',
                   'otherfile.txt': 'test2',
                   })
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('file-comments').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('file-comments-error').result,
                         'SUCCESS')
        self.assertEqual(len(A.comments), 3)
        comments = sorted(A.comments, key=lambda x: x['line'])
        self.assertEqual(comments[0],
                         {'file': 'otherfile.txt',
                          'line': 21,
                          'message': 'This is a much longer message.\n\n'
                          'With multiple paragraphs.\n',
                          'reviewer': {'email': 'zuul@example.com',
                                       'name': 'Zuul',
                                       'username': 'jenkins'}}
        )
        self.assertEqual(comments[1],
                         {'file': 'path/to/file.py',
                          'line': 42,
                          'message': 'line too long',
                          'reviewer': {'email': 'zuul@example.com',
                                       'name': 'Zuul',
                                       'username': 'jenkins'}}
        )
        self.assertEqual(comments[2],
                         {'file': 'path/to/file.py',
                          'line': 82,
                          'message': 'line too short',
                          'reviewer': {'email': 'zuul@example.com',
                                       'name': 'Zuul',
                                       'username': 'jenkins'}}
        )
        self.assertIn('expected a dictionary', A.messages[0],
                      "A should have a validation error reported")
        self.assertIn('invalid file missingfile.txt', A.messages[0],
                      "A should have file error reported")
