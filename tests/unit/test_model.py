# Copyright 2015 Red Hat, Inc.
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
import random

import fixtures
import testtools

from zuul import model
from zuul import configloader

from tests.base import BaseTestCase


class TestJob(BaseTestCase):

    def setUp(self):
        super(TestJob, self).setUp()
        self.project = model.Project('project', None)
        self.context = model.SourceContext(self.project, 'master',
                                           'test', True)

    @property
    def job(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout()
        project = model.Project('project', None)
        context = model.SourceContext(project, 'master', 'test', True)
        job = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'job',
            'irrelevant-files': [
                '^docs/.*$'
            ]})
        return job

    def test_change_matches_returns_false_for_matched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'docs/foo']
        self.assertFalse(self.job.changeMatches(change))

    def test_change_matches_returns_true_for_unmatched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'foo']
        self.assertTrue(self.job.changeMatches(change))

    def test_job_sets_defaults_for_boolean_attributes(self):
        self.assertIsNotNone(self.job.voting)

    def test_job_inheritance(self):
        # This is standard job inheritance.

        base_pre = model.PlaybookContext(self.context, 'base-pre')
        base_run = model.PlaybookContext(self.context, 'base-run')
        base_post = model.PlaybookContext(self.context, 'base-post')

        base = model.Job('base')
        base.timeout = 30
        base.pre_run = [base_pre]
        base.run = [base_run]
        base.post_run = [base_post]
        base.auth = dict(foo='bar', inherit=False)

        py27 = model.Job('py27')
        self.assertEqual(None, py27.timeout)
        py27.inheritFrom(base)
        self.assertEqual(30, py27.timeout)
        self.assertEqual(['base-pre'],
                         [x.path for x in py27.pre_run])
        self.assertEqual(['base-run'],
                         [x.path for x in py27.run])
        self.assertEqual(['base-post'],
                         [x.path for x in py27.post_run])
        self.assertEqual({}, py27.auth)

    def test_job_variants(self):
        # This simulates freezing a job.

        py27_pre = model.PlaybookContext(self.context, 'py27-pre')
        py27_run = model.PlaybookContext(self.context, 'py27-run')
        py27_post = model.PlaybookContext(self.context, 'py27-post')

        py27 = model.Job('py27')
        py27.timeout = 30
        py27.pre_run = [py27_pre]
        py27.run = [py27_run]
        py27.post_run = [py27_post]
        auth = dict(foo='bar', inherit=False)
        py27.auth = auth

        job = py27.copy()
        self.assertEqual(30, job.timeout)

        # Apply the diablo variant
        diablo = model.Job('py27')
        diablo.timeout = 40
        job.applyVariant(diablo)

        self.assertEqual(40, job.timeout)
        self.assertEqual(['py27-pre'],
                         [x.path for x in job.pre_run])
        self.assertEqual(['py27-run'],
                         [x.path for x in job.run])
        self.assertEqual(['py27-post'],
                         [x.path for x in job.post_run])
        self.assertEqual(auth, job.auth)

        # Set the job to final for the following checks
        job.final = True
        self.assertTrue(job.voting)

        good_final = model.Job('py27')
        good_final.voting = False
        job.applyVariant(good_final)
        self.assertFalse(job.voting)

        bad_final = model.Job('py27')
        bad_final.timeout = 600
        with testtools.ExpectedException(
                Exception,
                "Unable to modify final job"):
            job.applyVariant(bad_final)

    def test_job_inheritance_configloader(self):
        # TODO(jeblair): move this to a configloader test
        tenant = model.Tenant('tenant')
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project', None)
        context = model.SourceContext(project, 'master', 'test', True)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'base',
            'timeout': 30,
            'pre-run': 'base-pre',
            'post-run': 'base-post',
            'nodes': [{
                'name': 'controller',
                'image': 'base',
            }],
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'parent': 'base',
            'pre-run': 'py27-pre',
            'post-run': 'py27-post',
            'nodes': [{
                'name': 'controller',
                'image': 'new',
            }],
            'timeout': 40,
        })
        layout.addJob(python27)
        python27diablo = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'branches': [
                'stable/diablo'
            ],
            'pre-run': 'py27-diablo-pre',
            'run': 'py27-diablo',
            'post-run': 'py27-diablo-post',
            'nodes': [{
                'name': 'controller',
                'image': 'old',
            }],
            'timeout': 50,
        })
        layout.addJob(python27diablo)

        python27essex = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'branches': [
                'stable/essex'
            ],
            'pre-run': 'py27-essex-pre',
            'post-run': 'py27-essex-post',
        })
        layout.addJob(python27essex)

        project_config = configloader.ProjectParser.fromYaml(tenant, layout, [{
            '_source_context': context,
            'name': 'project',
            'gate': {
                'jobs': [
                    'python27'
                ]
            }
        }])
        layout.addProjectConfig(project_config, update_pipeline=False)

        change = model.Change(project)
        # Test master
        change.branch = 'master'
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertFalse(python27diablo.changeMatches(change))
        self.assertFalse(python27essex.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 40)
        nodes = job.nodeset.getNodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].image, 'new')
        self.assertEqual([x.path for x in job.pre_run],
                         ['playbooks/base-pre',
                          'playbooks/py27-pre'])
        self.assertEqual([x.path for x in job.post_run],
                         ['playbooks/py27-post',
                          'playbooks/base-post'])
        self.assertEqual([x.path for x in job.run],
                         ['playbooks/python27',
                          'playbooks/base'])

        # Test diablo
        change.branch = 'stable/diablo'
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertTrue(python27diablo.changeMatches(change))
        self.assertFalse(python27essex.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 50)
        nodes = job.nodeset.getNodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].image, 'old')
        self.assertEqual([x.path for x in job.pre_run],
                         ['playbooks/base-pre',
                          'playbooks/py27-pre',
                          'playbooks/py27-diablo-pre'])
        self.assertEqual([x.path for x in job.post_run],
                         ['playbooks/py27-diablo-post',
                          'playbooks/py27-post',
                          'playbooks/base-post'])
        self.assertEqual([x.path for x in job.run],
                         ['playbooks/py27-diablo']),

        # Test essex
        change.branch = 'stable/essex'
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertFalse(python27diablo.changeMatches(change))
        self.assertTrue(python27essex.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual([x.path for x in job.pre_run],
                         ['playbooks/base-pre',
                          'playbooks/py27-pre',
                          'playbooks/py27-essex-pre'])
        self.assertEqual([x.path for x in job.post_run],
                         ['playbooks/py27-essex-post',
                          'playbooks/py27-post',
                          'playbooks/base-post'])
        self.assertEqual([x.path for x in job.run],
                         ['playbooks/python27',
                          'playbooks/base'])

    def test_job_auth_inheritance(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout()
        project = model.Project('project', None)
        context = model.SourceContext(project, 'master', 'test', True)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        pypi_upload_without_inherit = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'pypi-upload-without-inherit',
                'parent': 'base',
                'timeout': 40,
                'auth': {
                    'secrets': [
                        'pypi-credentials',
                    ]
                }
            })
        layout.addJob(pypi_upload_without_inherit)
        pypi_upload_with_inherit = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'pypi-upload-with-inherit',
                'parent': 'base',
                'timeout': 40,
                'auth': {
                    'inherit': True,
                    'secrets': [
                        'pypi-credentials',
                    ]
                }
            })
        layout.addJob(pypi_upload_with_inherit)
        pypi_upload_with_inherit_false = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'pypi-upload-with-inherit-false',
                'parent': 'base',
                'timeout': 40,
                'auth': {
                    'inherit': False,
                    'secrets': [
                        'pypi-credentials',
                    ]
                }
            })
        layout.addJob(pypi_upload_with_inherit_false)
        in_repo_job_without_inherit = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'in-repo-job-without-inherit',
                'parent': 'pypi-upload-without-inherit',
            })
        layout.addJob(in_repo_job_without_inherit)
        in_repo_job_with_inherit = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'in-repo-job-with-inherit',
                'parent': 'pypi-upload-with-inherit',
            })
        layout.addJob(in_repo_job_with_inherit)
        in_repo_job_with_inherit_false = configloader.JobParser.fromYaml(
            tenant, layout, {
                '_source_context': context,
                'name': 'in-repo-job-with-inherit-false',
                'parent': 'pypi-upload-with-inherit-false',
            })
        layout.addJob(in_repo_job_with_inherit_false)

        self.assertNotIn('auth', in_repo_job_without_inherit.auth)
        self.assertIn('secrets', in_repo_job_with_inherit.auth)
        self.assertEquals(in_repo_job_with_inherit.auth['secrets'],
                          ['pypi-credentials'])
        self.assertNotIn('auth', in_repo_job_with_inherit_false.auth)

    def test_job_inheritance_job_tree(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project', None)
        context = model.SourceContext(project, 'master', 'test', True)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
        })
        layout.addJob(python27)
        python27diablo = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'branches': [
                'stable/diablo'
            ],
            'timeout': 50,
        })
        layout.addJob(python27diablo)

        project_config = configloader.ProjectParser.fromYaml(tenant, layout, [{
            '_source_context': context,
            'name': 'project',
            'gate': {
                'jobs': [
                    {'python27': {'timeout': 70}}
                ]
            }
        }])
        layout.addProjectConfig(project_config, update_pipeline=False)

        change = model.Change(project)
        change.branch = 'master'
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertFalse(python27diablo.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 70)

        change.branch = 'stable/diablo'
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertTrue(python27diablo.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 70)

    def test_inheritance_keeps_matchers(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project', None)
        context = model.SourceContext(project, 'master', 'test', True)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': context,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
            'irrelevant-files': ['^ignored-file$'],
        })
        layout.addJob(python27)

        project_config = configloader.ProjectParser.fromYaml(tenant, layout, [{
            '_source_context': context,
            'name': 'project',
            'gate': {
                'jobs': [
                    'python27',
                ]
            }
        }])
        layout.addProjectConfig(project_config, update_pipeline=False)

        change = model.Change(project)
        change.branch = 'master'
        change.files = ['/COMMIT_MSG', 'ignored-file']
        item = queue.enqueueChange(change)
        item.current_build_set.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertFalse(python27.changeMatches(change))

        item.freezeJobTree()
        self.assertEqual([], item.getJobs())

    def test_job_source_project(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout()
        base_project = model.Project('base_project', None)
        base_context = model.SourceContext(base_project, 'master',
                                           'test', True)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': base_context,
            'name': 'base',
        })
        layout.addJob(base)

        other_project = model.Project('other_project', None)
        other_context = model.SourceContext(other_project, 'master',
                                            'test', True)
        base2 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': other_context,
            'name': 'base',
        })
        with testtools.ExpectedException(
                Exception,
                "Job base in other_project is not permitted "
                "to shadow job base in base_project"):
            layout.addJob(base2)


class TestJobTimeData(BaseTestCase):
    def setUp(self):
        super(TestJobTimeData, self).setUp()
        self.tmp_root = self.useFixture(fixtures.TempDir(
            rootdir=os.environ.get("ZUUL_TEST_ROOT"))
        ).path

    def test_empty_timedata(self):
        path = os.path.join(self.tmp_root, 'job-name')
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(path + '.tmp'))
        td = model.JobTimeData(path)
        self.assertEqual(td.success_times, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(td.failure_times, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(td.results, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    def test_save_reload(self):
        path = os.path.join(self.tmp_root, 'job-name')
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(path + '.tmp'))
        td = model.JobTimeData(path)
        self.assertEqual(td.success_times, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(td.failure_times, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(td.results, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        success_times = []
        failure_times = []
        results = []
        for x in range(10):
            success_times.append(int(random.random() * 1000))
            failure_times.append(int(random.random() * 1000))
            results.append(0)
            results.append(1)
        random.shuffle(results)
        s = f = 0
        for result in results:
            if result:
                td.add(failure_times[f], 'FAILURE')
                f += 1
            else:
                td.add(success_times[s], 'SUCCESS')
                s += 1
        self.assertEqual(td.success_times, success_times)
        self.assertEqual(td.failure_times, failure_times)
        self.assertEqual(td.results, results[10:])
        td.save()
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + '.tmp'))
        td = model.JobTimeData(path)
        td.load()
        self.assertEqual(td.success_times, success_times)
        self.assertEqual(td.failure_times, failure_times)
        self.assertEqual(td.results, results[10:])


class TestTimeDataBase(BaseTestCase):
    def setUp(self):
        super(TestTimeDataBase, self).setUp()
        self.tmp_root = self.useFixture(fixtures.TempDir(
            rootdir=os.environ.get("ZUUL_TEST_ROOT"))
        ).path
        self.db = model.TimeDataBase(self.tmp_root)

    def test_timedatabase(self):
        self.assertEqual(self.db.getEstimatedTime('job-name'), 0)
        self.db.update('job-name', 50, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime('job-name'), 50)
        self.db.update('job-name', 100, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime('job-name'), 75)
        for x in range(10):
            self.db.update('job-name', 100, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime('job-name'), 100)
