#!/usr/bin/env python

# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import json
import os
import textwrap

import testtools

import zuul.configloader
from zuul.lib import encryption
from tests.base import AnsibleZuulTestCase, ZuulTestCase, FIXTURE_DIR


class TestMultipleTenants(AnsibleZuulTestCase):
    # A temporary class to hold new tests while others are disabled

    tenant_config_file = 'config/multi-tenant/main.yaml'

    def test_multiple_tenants(self):
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project1-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('python27').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('tenant-one-gate', A.messages[1],
                      "A should transit tenant-one gate")
        self.assertNotIn('tenant-two-gate', A.messages[1],
                         "A should *not* transit tenant-two gate")

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('python27',
                                                'org/project2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project2-test1').result,
                         'SUCCESS')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2,
                         "B should report start and success")
        self.assertIn('tenant-two-gate', B.messages[1],
                      "B should transit tenant-two gate")
        self.assertNotIn('tenant-one-gate', B.messages[1],
                         "B should *not* transit tenant-one gate")

        self.assertEqual(A.reported, 2, "Activity in tenant two should"
                         "not affect tenant one")


class TestFinal(ZuulTestCase):

    tenant_config_file = 'config/final/main.yaml'

    def test_final_variant_ok(self):
        # test clean usage of final parent job
        in_repo_conf = textwrap.dedent(
            """
            - project:
                name: org/project
                check:
                  jobs:
                    - job-final
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '1')

    def test_final_variant_error(self):
        # test misuse of final parent job
        in_repo_conf = textwrap.dedent(
            """
            - project:
                name: org/project
                check:
                  jobs:
                    - job-final:
                        vars:
                          dont_override_this: bar
            """)
        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # The second patch tried to override some variables.
        # Thus it should fail.
        self.assertEqual(A.reported, 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertIn('Unable to modify final job', A.messages[0])

    def test_final_inheritance(self):
        # test misuse of final parent job
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test
                parent: job-final

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # The second patch tried to override some variables.
        # Thus it should fail.
        self.assertEqual(A.reported, 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertIn('Unable to inherit from final job', A.messages[0])


class TestInRepoConfig(ZuulTestCase):
    # A temporary class to hold new tests while others are disabled

    config_file = 'zuul-connections-gerrit-and-github.conf'
    tenant_config_file = 'config/in-repo/main.yaml'

    def test_in_repo_config(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('tenant-one-gate', A.messages[1],
                      "A should transit tenant-one gate")

    def test_dynamic_config(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                tenant-one-gate:
                  jobs:
                    - project-test2
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('tenant-one-gate', A.messages[1],
                      "A should transit tenant-one gate")
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1')])

        self.fake_gerrit.addEvent(A.getChangeMergedEvent())
        self.waitUntilSettled()

        # Now that the config change is landed, it should be live for
        # subsequent changes.
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1')])

    def test_dynamic_config_non_existing_job(self):
        """Test that requesting a non existent job fails"""
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - project:
                name: org/project
                check:
                  jobs:
                    - non-existent-job
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('Job non-existent-job not defined', A.messages[0],
                      "A should have failed the check pipeline")
        self.assertHistory([])

    def test_dynamic_config_non_existing_job_in_template(self):
        """Test that requesting a non existent job fails"""
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - project-template:
                name: test-template
                check:
                  jobs:
                    - non-existent-job

            - project:
                name: org/project
                templates:
                  - test-template
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('Job non-existent-job not defined', A.messages[0],
                      "A should have failed the check pipeline")
        self.assertHistory([])

    def test_dynamic_config_new_patchset(self):
        self.executor_server.hold_jobs_in_build = True

        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test2
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        items = check_pipeline.getAllItems()
        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '1')
        self.assertTrue(items[0].live)

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test1
                    - project-test2
            """)
        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}

        A.addPatchset(files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))

        self.waitUntilSettled()

        items = check_pipeline.getAllItems()
        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '2')
        self.assertTrue(items[0].live)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release('project-test1')
        self.waitUntilSettled()
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-test2', result='ABORTED', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,2'),
            dict(name='project-test2', result='SUCCESS', changes='1,2')])

    def test_in_repo_branch(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                tenant-one-gate:
                  jobs:
                    - project-test2
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        self.create_branch('org/project', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable'))
        A = self.fake_gerrit.addFakeChange('org/project', 'stable', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('tenant-one-gate', A.messages[1],
                      "A should transit tenant-one gate")
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1')])
        self.fake_gerrit.addEvent(A.getChangeMergedEvent())
        self.waitUntilSettled()

        # The config change should not affect master.
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1')])

        # The config change should be live for further changes on
        # stable.
        C = self.fake_gerrit.addFakeChange('org/project', 'stable', 'C')
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1'),
            dict(name='project-test2', result='SUCCESS', changes='3,1')])

    def test_crd_dynamic_config_branch(self):
        # Test that we can create a job in one repo and be able to use
        # it from a different branch on a different repo.

        self.create_branch('org/project1', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project1', 'stable'))

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test2
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)

        second_repo_conf = textwrap.dedent(
            """
            - project:
                name: org/project1
                check:
                  jobs:
                    - project-test2
            """)

        second_file_dict = {'.zuul.yaml': second_repo_conf}
        B = self.fake_gerrit.addFakeChange('org/project1', 'stable', 'B',
                                           files=second_file_dict)
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1, "A should report")
        self.assertHistory([
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1 2,1'),
        ])

    def test_yaml_list_error(self):
        in_repo_conf = textwrap.dedent(
            """
            job: foo
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('not a list', A.messages[0],
                      "A should have a syntax error reported")

    def test_yaml_dict_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('not a dictionary', A.messages[0],
                      "A should have a syntax error reported")

    def test_yaml_key_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
              name: project-test2
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('has more than one key', A.messages[0],
                      "A should have a syntax error reported")

    def test_yaml_unknown_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - foobar:
                foo: bar
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('not recognized', A.messages[0],
                      "A should have a syntax error reported")

    def test_untrusted_syntax_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test2
                foo: error
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('syntax error', A.messages[0],
                      "A should have a syntax error reported")

    def test_trusted_syntax_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test2
                foo: error
            """)

        file_dict = {'zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('syntax error', A.messages[0],
                      "A should have a syntax error reported")

    def test_untrusted_yaml_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
            foo: error
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('syntax error', A.messages[0],
                      "A should have a syntax error reported")

    def test_untrusted_shadow_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: common-config-test
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('not permitted to shadow', A.messages[0],
                      "A should have a syntax error reported")

    def test_untrusted_pipeline_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - pipeline:
                name: test
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('Pipelines may not be defined', A.messages[0],
                      "A should have a syntax error reported")

    def test_untrusted_project_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - project:
                name: org/project1
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('the only project definition permitted', A.messages[0],
                      "A should have a syntax error reported")

    def test_duplicate_node_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - nodeset:
                name: duplicate
                nodes:
                  - name: compute
                    label: foo
                  - name: compute
                    label: foo
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('appears multiple times', A.messages[0],
                      "A should have a syntax error reported")

    def test_duplicate_group_error(self):
        in_repo_conf = textwrap.dedent(
            """
            - nodeset:
                name: duplicate
                nodes:
                  - name: compute
                    label: foo
                groups:
                  - name: group
                    nodes: compute
                  - name: group
                    nodes: compute
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('appears multiple times', A.messages[0],
                      "A should have a syntax error reported")

    def test_multi_repo(self):
        downstream_repo_conf = textwrap.dedent(
            """
            - project:
                name: org/project1
                tenant-one-gate:
                  jobs:
                    - project-test1

            - job:
                name: project1-test1
                parent: project-test1
            """)

        file_dict = {'.zuul.yaml': downstream_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.fake_gerrit.addEvent(A.getChangeMergedEvent())
        self.waitUntilSettled()

        upstream_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                tenant-one-gate:
                  jobs:
                    - project-test1
            """)

        file_dict = {'.zuul.yaml': upstream_repo_conf}
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B',
                                           files=file_dict)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(B.data['status'], 'MERGED')
        self.fake_gerrit.addEvent(B.getChangeMergedEvent())
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        # Ensure the latest change is reflected in the config; if it
        # isn't this will raise an exception.
        tenant.layout.getJob('project-test2')

    def test_pipeline_error(self):
        with open(os.path.join(FIXTURE_DIR,
                               'config/in-repo/git/',
                               'common-config/zuul.yaml')) as f:
            base_common_config = f.read()

        in_repo_conf_A = textwrap.dedent(
            """
            - pipeline:
                name: periodic
                foo: error
            """)

        file_dict = {'zuul.yaml': None,
                     'zuul.d/main.yaml': base_common_config,
                     'zuul.d/test1.yaml': in_repo_conf_A}
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertIn('syntax error',
                      A.messages[0],
                      "A should have an error reported")

    def test_change_series_error(self):
        with open(os.path.join(FIXTURE_DIR,
                               'config/in-repo/git/',
                               'common-config/zuul.yaml')) as f:
            base_common_config = f.read()

        in_repo_conf_A = textwrap.dedent(
            """
            - pipeline:
                name: periodic
                foo: error
            """)

        file_dict = {'zuul.yaml': None,
                     'zuul.d/main.yaml': base_common_config,
                     'zuul.d/test1.yaml': in_repo_conf_A}
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A',
                                           files=file_dict)

        in_repo_conf_B = textwrap.dedent(
            """
            - job:
                name: project-test2
                foo: error
            """)

        file_dict = {'zuul.yaml': None,
                     'zuul.d/main.yaml': base_common_config,
                     'zuul.d/test1.yaml': in_repo_conf_A,
                     'zuul.d/test2.yaml': in_repo_conf_B}
        B = self.fake_gerrit.addFakeChange('common-config', 'master', 'B',
                                           files=file_dict)
        B.setDependsOn(A, 1)
        C = self.fake_gerrit.addFakeChange('common-config', 'master', 'C')
        C.setDependsOn(B, 1)
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(C.reported, 1,
                         "C should report failure")
        self.assertIn('depends on a change that failed to merge',
                      C.messages[0],
                      "C should have an error reported")


class TestInRepoJoin(ZuulTestCase):
    # In this config, org/project is not a member of any pipelines, so
    # that we may test the changes that cause it to join them.

    tenant_config_file = 'config/in-repo-join/main.yaml'

    def test_dynamic_dependent_pipeline(self):
        # Test dynamically adding a project to a
        # dependent pipeline for the first time
        self.executor_server.hold_jobs_in_build = True

        tenant = self.sched.abide.tenants.get('tenant-one')
        gate_pipeline = tenant.layout.pipelines['gate']

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2

            - project:
                name: org/project
                gate:
                  jobs:
                    - project-test2
            """)

        in_repo_playbook = textwrap.dedent(
            """
            - hosts: all
              tasks: []
            """)

        file_dict = {'.zuul.yaml': in_repo_conf,
                     'playbooks/project-test2.yaml': in_repo_playbook}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        items = gate_pipeline.getAllItems()
        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '1')
        self.assertTrue(items[0].live)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        # Make sure the dynamic queue got cleaned up
        self.assertEqual(gate_pipeline.queues, [])

    def test_dynamic_dependent_pipeline_failure(self):
        # Test that a change behind a failing change adding a project
        # to a dependent pipeline is dequeued.
        self.executor_server.hold_jobs_in_build = True

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - project:
                name: org/project
                gate:
                  jobs:
                    - project-test1
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.executor_server.failJob('project-test1', A)
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.orderedRelease()
        self.waitUntilSettled()
        self.assertEqual(A.reported, 2,
                         "A should report start and failure")
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.reported, 1,
                         "B should report start")
        self.assertHistory([
            dict(name='project-test1', result='FAILURE', changes='1,1'),
            dict(name='project-test1', result='ABORTED', changes='1,1 2,1'),
        ], ordered=False)

    def test_dynamic_dependent_pipeline_absent(self):
        # Test that a series of dependent changes don't report merge
        # failures to a pipeline they aren't in.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.setDependsOn(A, 1)

        A.addApproval('Code-Review', 2)
        A.addApproval('Approved', 1)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 0,
                         "A should not report")
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.reported, 0,
                         "B should not report")
        self.assertEqual(B.data['status'], 'NEW')
        self.assertHistory([])


class TestAnsible(AnsibleZuulTestCase):
    # A temporary class to hold new tests while others are disabled

    tenant_config_file = 'config/ansible/main.yaml'

    def test_playbook(self):
        # Keep the jobdir around so we can inspect contents if an
        # assert fails.
        self.executor_server.keep_jobdir = True
        # Output extra ansible info so we might see errors.
        self.executor_server.verbose = True
        # Add a site variables file, used by check-vars
        path = os.path.join(FIXTURE_DIR, 'config', 'ansible',
                            'variables.yaml')
        self.config.set('executor', 'variables', path)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        build_timeout = self.getJobFromHistory('timeout')
        with self.jobLog(build_timeout):
            self.assertEqual(build_timeout.result, 'TIMED_OUT')
        build_faillocal = self.getJobFromHistory('faillocal')
        with self.jobLog(build_faillocal):
            self.assertEqual(build_faillocal.result, 'FAILURE')
        build_failpost = self.getJobFromHistory('failpost')
        with self.jobLog(build_failpost):
            self.assertEqual(build_failpost.result, 'POST_FAILURE')
        build_check_vars = self.getJobFromHistory('check-vars')
        with self.jobLog(build_check_vars):
            self.assertEqual(build_check_vars.result, 'SUCCESS')
        build_check_secret_names = self.getJobFromHistory('check-secret-names')
        with self.jobLog(build_check_secret_names):
            self.assertEqual(build_check_secret_names.result, 'SUCCESS')
        build_hello = self.getJobFromHistory('hello-world')
        with self.jobLog(build_hello):
            self.assertEqual(build_hello.result, 'SUCCESS')
        build_python27 = self.getJobFromHistory('python27')
        with self.jobLog(build_python27):
            self.assertEqual(build_python27.result, 'SUCCESS')
            flag_path = os.path.join(self.test_root,
                                     build_python27.uuid + '.flag')
            self.assertTrue(os.path.exists(flag_path))
            copied_path = os.path.join(self.test_root, build_python27.uuid +
                                       '.copied')
            self.assertTrue(os.path.exists(copied_path))
            failed_path = os.path.join(self.test_root, build_python27.uuid +
                                       '.failed')
            self.assertFalse(os.path.exists(failed_path))
            pre_flag_path = os.path.join(self.test_root, build_python27.uuid +
                                         '.pre.flag')
            self.assertTrue(os.path.exists(pre_flag_path))
            post_flag_path = os.path.join(self.test_root, build_python27.uuid +
                                          '.post.flag')
            self.assertTrue(os.path.exists(post_flag_path))
            bare_role_flag_path = os.path.join(self.test_root,
                                               build_python27.uuid +
                                               '.bare-role.flag')
            self.assertTrue(os.path.exists(bare_role_flag_path))
            secrets_path = os.path.join(self.test_root,
                                        build_python27.uuid + '.secrets')
            with open(secrets_path) as f:
                self.assertEqual(f.read(), "test-username test-password")

            msg = A.messages[0]
            success = "{} https://success.example.com/zuul-logs/{}"
            fail = "{} https://failure.example.com/zuul-logs/{}"
            self.assertIn(success.format("python27", build_python27.uuid), msg)
            self.assertIn(fail.format("faillocal", build_faillocal.uuid), msg)
            self.assertIn(success.format("check-vars",
                                         build_check_vars.uuid), msg)
            self.assertIn(success.format("hello-world", build_hello.uuid), msg)
            self.assertIn(fail.format("timeout", build_timeout.uuid), msg)
            self.assertIn(fail.format("failpost", build_failpost.uuid), msg)

    def _add_job(self, job_name):
        conf = textwrap.dedent(
            """
            - job:
                name: %s

            - project:
                name: org/plugin-project
                check:
                  jobs:
                    - %s
            """ % (job_name, job_name))

        file_dict = {'.zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/plugin-project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

    def test_plugins(self):
        # Keep the jobdir around so we can inspect contents if an
        # assert fails.
        self.executor_server.keep_jobdir = True
        # Output extra ansible info so we might see errors.
        self.executor_server.verbose = True

        count = 0
        plugin_tests = [
            ('passwd', 'FAILURE'),
            ('cartesian', 'SUCCESS'),
            ('consul_kv', 'FAILURE'),
            ('credstash', 'FAILURE'),
            ('csvfile_good', 'SUCCESS'),
            ('csvfile_bad', 'FAILURE'),
            ('uri_bad_path', 'FAILURE'),
            ('uri_bad_scheme', 'FAILURE'),
            ('block_local_override', 'FAILURE'),
            ('file_local_good', 'SUCCESS'),
            ('file_local_bad', 'FAILURE'),
        ]
        for job_name, result in plugin_tests:
            count += 1
            self._add_job(job_name)

            job = self.getJobFromHistory(job_name)
            with self.jobLog(job):
                self.assertEqual(count, len(self.history))
                build = self.history[-1]
                self.assertEqual(build.result, result)

        # TODOv3(jeblair): parse the ansible output and verify we're
        # getting the exception we expect.


class TestPrePlaybooks(AnsibleZuulTestCase):
    # A temporary class to hold new tests while others are disabled

    tenant_config_file = 'config/pre-playbook/main.yaml'

    def test_pre_playbook_fail(self):
        # Test that we run the post playbooks (but not the actual
        # playbook) when a pre-playbook fails.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        build = self.getJobFromHistory('python27')
        self.assertIsNone(build.result)
        self.assertIn('RETRY_LIMIT', A.messages[0])
        flag_path = os.path.join(self.test_root, build.uuid +
                                 '.main.flag')
        self.assertFalse(os.path.exists(flag_path))
        pre_flag_path = os.path.join(self.test_root, build.uuid +
                                     '.pre.flag')
        self.assertFalse(os.path.exists(pre_flag_path))
        post_flag_path = os.path.join(self.test_root, build.uuid +
                                      '.post.flag')
        self.assertTrue(os.path.exists(post_flag_path),
                        "The file %s should exist" % post_flag_path)


class TestBrokenConfig(ZuulTestCase):
    # Test that we get an appropriate syntax error if we start with a
    # broken config.

    tenant_config_file = 'config/broken/main.yaml'

    def setUp(self):
        with testtools.ExpectedException(
                zuul.configloader.ConfigurationSyntaxError,
                "\nZuul encountered a syntax error"):
            super(TestBrokenConfig, self).setUp()

    def test_broken_config_on_startup(self):
        pass


class TestProjectKeys(ZuulTestCase):
    # Test that we can generate project keys

    # Normally the test infrastructure copies a static key in place
    # for each project before starting tests.  This saves time because
    # Zuul's automatic key-generation on startup can be slow.  To make
    # sure we exercise that code, in this test we allow Zuul to create
    # keys for the project on startup.
    create_project_keys = True
    config_file = 'zuul-connections-gerrit-and-github.conf'
    tenant_config_file = 'config/in-repo/main.yaml'

    def test_key_generation(self):
        key_root = os.path.join(self.state_root, 'keys')
        private_key_file = os.path.join(key_root, 'gerrit/org/project.pem')
        # Make sure that a proper key was created on startup
        with open(private_key_file, "rb") as f:
            private_key, public_key = \
                encryption.deserialize_rsa_keypair(f.read())

        with open(os.path.join(FIXTURE_DIR, 'private.pem')) as i:
            fixture_private_key = i.read()

        # Make sure that we didn't just end up with the static fixture
        # key
        self.assertNotEqual(fixture_private_key, private_key)

        # Make sure it's the right length
        self.assertEqual(4096, private_key.key_size)


class RoleTestCase(ZuulTestCase):
    def _assertRolePath(self, build, playbook, content):
        path = os.path.join(self.test_root, build.uuid,
                            'ansible', playbook, 'ansible.cfg')
        roles_paths = []
        with open(path) as f:
            for line in f:
                if line.startswith('roles_path'):
                    roles_paths.append(line)
        print(roles_paths)
        if content:
            self.assertEqual(len(roles_paths), 1,
                             "Should have one roles_path line in %s" %
                             (playbook,))
            self.assertIn(content, roles_paths[0])
        else:
            self.assertEqual(len(roles_paths), 0,
                             "Should have no roles_path line in %s" %
                             (playbook,))


class TestRoles(RoleTestCase):
    tenant_config_file = 'config/roles/main.yaml'

    def test_role(self):
        # This exercises a proposed change to a role being checked out
        # and used.
        A = self.fake_gerrit.addFakeChange('bare-role', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='project-test', result='SUCCESS', changes='1,1 2,1'),
        ])

    def test_role_inheritance(self):
        self.executor_server.hold_jobs_in_build = True
        conf = textwrap.dedent(
            """
            - job:
                name: parent
                roles:
                  - zuul: bare-role
                pre-run: playbooks/parent-pre
                post-run: playbooks/parent-post

            - job:
                name: project-test
                parent: parent
                roles:
                  - zuul: org/project

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test
            """)

        file_dict = {'.zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        build = self.getBuildByName('project-test')
        self._assertRolePath(build, 'pre_playbook_0', 'role_0')
        self._assertRolePath(build, 'playbook_0', 'role_0')
        self._assertRolePath(build, 'playbook_0', 'role_1')
        self._assertRolePath(build, 'post_playbook_0', 'role_0')

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-test', result='SUCCESS', changes='1,1'),
        ])

    def test_role_error(self):
        conf = textwrap.dedent(
            """
            - job:
                name: project-test
                roles:
                  - zuul: common-config

            - project:
                name: org/project
                check:
                  jobs:
                    - project-test
            """)

        file_dict = {'.zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertIn(
            '- project-test project-test : ERROR Unable to find role',
            A.messages[-1])


class TestImplicitRoles(RoleTestCase):
    tenant_config_file = 'config/implicit-roles/main.yaml'

    def test_missing_roles(self):
        # Test implicit and explicit roles for a project which does
        # not have roles.  The implicit role should be silently
        # ignored since the project doesn't supply roles, but if a
        # user declares an explicit role, it should error.
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/norole-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        build = self.getBuildByName('implicit-role-fail')
        self._assertRolePath(build, 'playbook_0', None)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        # The retry_limit doesn't get recorded
        self.assertHistory([
            dict(name='implicit-role-fail', result='SUCCESS', changes='1,1'),
        ])

    def test_roles(self):
        # Test implicit and explicit roles for a project which does
        # have roles.  In both cases, we should end up with the role
        # in the path.  In the explicit case, ensure we end up with
        # the name we specified.
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/role-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        build = self.getBuildByName('implicit-role-ok')
        self._assertRolePath(build, 'playbook_0', 'role_0')

        build = self.getBuildByName('explicit-role-ok')
        self._assertRolePath(build, 'playbook_0', 'role_0')

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='implicit-role-ok', result='SUCCESS', changes='1,1'),
            dict(name='explicit-role-ok', result='SUCCESS', changes='1,1'),
        ], ordered=False)


class TestShadow(ZuulTestCase):
    tenant_config_file = 'config/shadow/main.yaml'

    def test_shadow(self):
        # Test that a repo is allowed to shadow another's job definitions.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='test1', result='SUCCESS', changes='1,1'),
            dict(name='test2', result='SUCCESS', changes='1,1'),
        ], ordered=False)


class TestDataReturn(AnsibleZuulTestCase):
    tenant_config_file = 'config/data-return/main.yaml'

    def test_data_return(self):
        # This exercises a proposed change to a role being checked out
        # and used.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='data-return', result='SUCCESS', changes='1,1'),
            dict(name='data-return-relative', result='SUCCESS', changes='1,1'),
        ], ordered=False)
        self.assertIn('- data-return http://example.com/test/log/url/',
                      A.messages[-1])
        self.assertIn('- data-return-relative '
                      'http://example.com/test/log/url/docs/index.html',
                      A.messages[-1])


class TestDiskAccounting(AnsibleZuulTestCase):
    config_file = 'zuul-disk-accounting.conf'
    tenant_config_file = 'config/disk-accountant/main.yaml'

    def test_disk_accountant_kills_job(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='dd-big-empty-file', result='ABORTED', changes='1,1')])


class TestMaxNodesPerJob(AnsibleZuulTestCase):
    tenant_config_file = 'config/multi-tenant/main.yaml'

    def test_max_timeout_exceeded(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: test-job
                nodeset:
                  nodes:
                    - name: node01
                      label: fake
                    - name: node02
                      label: fake
                    - name: node03
                      label: fake
                    - name: node04
                      label: fake
                    - name: node05
                      label: fake
                    - name: node06
                      label: fake
            """)
        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertIn('The job "test-job" exceeds tenant max-nodes-per-job 5.',
                      A.messages[0], "A should fail because of nodes limit")

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertNotIn("exceeds tenant max-nodes", B.messages[0],
                         "B should not fail because of nodes limit")


class TestMaxTimeout(AnsibleZuulTestCase):
    tenant_config_file = 'config/multi-tenant/main.yaml'

    def test_max_nodes_reached(self):
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: test-job
                timeout: 3600
            """)
        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertIn('The job "test-job" exceeds tenant max-job-timeout',
                      A.messages[0], "A should fail because of timeout limit")

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertNotIn("exceeds tenant max-job-timeout", B.messages[0],
                         "B should not fail because of timeout limit")


class TestBaseJobs(ZuulTestCase):
    tenant_config_file = 'config/base-jobs/main.yaml'

    def test_multiple_base_jobs(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='my-job', result='SUCCESS', changes='1,1'),
            dict(name='other-job', result='SUCCESS', changes='1,1'),
        ], ordered=False)
        self.assertEqual(self.getJobFromHistory('my-job').
                         parameters['zuul']['jobtags'],
                         ['mybase'])
        self.assertEqual(self.getJobFromHistory('other-job').
                         parameters['zuul']['jobtags'],
                         ['otherbase'])

    def test_untrusted_base_job(self):
        """Test that a base job may not be defined in an untrusted repo"""
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: fail-base
                parent: null
            """)

        file_dict = {'.zuul.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1,
                         "A should report failure")
        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('Base jobs must be defined in config projects',
                      A.messages[0])
        self.assertHistory([])


class TestSecretLeaks(AnsibleZuulTestCase):
    tenant_config_file = 'config/secret-leaks/main.yaml'

    def searchForContent(self, path, content):
        matches = []
        for (dirpath, dirnames, filenames) in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                with open(filepath, 'rb') as f:
                    if content in f.read():
                        matches.append(filepath[len(path):])
        return matches

    def _test_secret_file(self):
        # Or rather -- test that they *don't* leak.
        # Keep the jobdir around so we can inspect contents.
        self.executor_server.keep_jobdir = True
        conf = textwrap.dedent(
            """
            - project:
                name: org/project
                check:
                  jobs:
                    - secret-file
            """)

        file_dict = {'.zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='secret-file', result='SUCCESS', changes='1,1'),
        ], ordered=False)
        matches = self.searchForContent(self.history[0].jobdir.root,
                                        b'test-password')
        self.assertEqual(set(['/work/secret-file.txt']),
                         set(matches))

    def test_secret_file(self):
        self._test_secret_file()

    def test_secret_file_verbose(self):
        # Output extra ansible info to exercise alternate logging code
        # paths.
        self.executor_server.verbose = True
        self._test_secret_file()

    def _test_secret_file_fail(self):
        # Or rather -- test that they *don't* leak.
        # Keep the jobdir around so we can inspect contents.
        self.executor_server.keep_jobdir = True
        conf = textwrap.dedent(
            """
            - project:
                name: org/project
                check:
                  jobs:
                    - secret-file-fail
            """)

        file_dict = {'.zuul.yaml': conf}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='secret-file-fail', result='FAILURE', changes='1,1'),
        ], ordered=False)
        matches = self.searchForContent(self.history[0].jobdir.root,
                                        b'test-password')
        self.assertEqual(set(['/work/failure-file.txt']),
                         set(matches))

    def test_secret_file_fail(self):
        self._test_secret_file_fail()

    def test_secret_file_fail_verbose(self):
        # Output extra ansible info to exercise alternate logging code
        # paths.
        self.executor_server.verbose = True
        self._test_secret_file_fail()


class TestJobOutput(AnsibleZuulTestCase):
    tenant_config_file = 'config/job-output/main.yaml'

    def _get_file(self, build, path):
        p = os.path.join(build.jobdir.root, path)
        with open(p) as f:
            return f.read()

    def test_job_output(self):
        # Verify that command standard output appears in the job output

        # This currently only verifies we receive output from
        # localhost.  Notably, it does not verify we receive output
        # via zuul_console streaming.
        self.executor_server.keep_jobdir = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='job-output', result='SUCCESS', changes='1,1'),
        ], ordered=False)

        token = 'Standard output test %s' % (self.history[0].jobdir.src_root)
        j = json.loads(self._get_file(self.history[0],
                                      'work/logs/job-output.json'))
        self.assertEqual(token,
                         j[0]['plays'][0]['tasks'][0]
                         ['hosts']['localhost']['stdout'])

        print(self._get_file(self.history[0],
                             'work/logs/job-output.txt'))
        self.assertIn(token,
                      self._get_file(self.history[0],
                                     'work/logs/job-output.txt'))
