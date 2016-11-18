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

    @property
    def job(self):
        layout = model.Layout()
        job = configloader.JobParser.fromYaml(layout, {
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
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project')

        base = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
        })
        layout.addJob(python27)
        python27diablo = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'python27',
            'branches': [
                'stable/diablo'
            ],
            'timeout': 50,
        })
        layout.addJob(python27diablo)

        project_config = configloader.ProjectParser.fromYaml(layout, {
            'name': 'project',
            'gate': {
                'jobs': [
                    'python27'
                ]
            }
        })
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
        self.assertEqual(job.timeout, 40)

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
        self.assertEqual(job.timeout, 50)

    def test_job_auth_inheritance(self):
        layout = model.Layout()
        project = model.Project('project')

        base = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        pypi_upload_without_inherit = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'pypi-upload-without-inherit',
            'parent': 'base',
            'timeout': 40,
            'auth': {
                'password': {
                    'pypipassword': 'dummypassword'
                }
            }
        })
        layout.addJob(pypi_upload_without_inherit)
        pypi_upload_with_inherit = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'pypi-upload-with-inherit',
            'parent': 'base',
            'timeout': 40,
            'auth': {
                'inherit': True,
                'password': {
                    'pypipassword': 'dummypassword'
                }
            }
        })
        layout.addJob(pypi_upload_with_inherit)
        pypi_upload_with_inherit_false = configloader.JobParser.fromYaml(
            layout, {
                '_source_project': project,
                'name': 'pypi-upload-with-inherit-false',
                'parent': 'base',
                'timeout': 40,
                'auth': {
                    'inherit': False,
                    'password': {
                        'pypipassword': 'dummypassword'
                    }
                }
            })
        layout.addJob(pypi_upload_with_inherit_false)
        in_repo_job_without_inherit = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'in-repo-job-without-inherit',
            'parent': 'pypi-upload-without-inherit',
        })
        layout.addJob(in_repo_job_without_inherit)
        in_repo_job_with_inherit = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'in-repo-job-with-inherit',
            'parent': 'pypi-upload-with-inherit',
        })
        layout.addJob(in_repo_job_with_inherit)
        in_repo_job_with_inherit_false = configloader.JobParser.fromYaml(
            layout, {
                '_source_project': project,
                'name': 'in-repo-job-with-inherit-false',
                'parent': 'pypi-upload-with-inherit-false',
            })
        layout.addJob(in_repo_job_with_inherit_false)

        self.assertNotIn('auth', in_repo_job_without_inherit.auth)
        self.assertIn('password', in_repo_job_with_inherit.auth)
        self.assertEquals(in_repo_job_with_inherit.auth['password'],
                          {'pypipassword': 'dummypassword'})
        self.assertNotIn('auth', in_repo_job_with_inherit_false.auth)

    def test_job_inheritance_job_tree(self):
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project')

        base = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
        })
        layout.addJob(python27)
        python27diablo = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'python27',
            'branches': [
                'stable/diablo'
            ],
            'timeout': 50,
        })
        layout.addJob(python27diablo)

        project_config = configloader.ProjectParser.fromYaml(layout, {
            'name': 'project',
            'gate': {
                'jobs': [
                    {'python27': {'timeout': 70}}
                ]
            }
        })
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
        layout = model.Layout()

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project')

        base = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'base',
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(layout, {
            '_source_project': project,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
            'irrelevant-files': ['^ignored-file$'],
        })
        layout.addJob(python27)

        project_config = configloader.ProjectParser.fromYaml(layout, {
            'name': 'project',
            'gate': {
                'jobs': [
                    'python27',
                ]
            }
        })
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
        layout = model.Layout()
        base_project = model.Project('base_project')
        base = configloader.JobParser.fromYaml(layout, {
            '_source_project': base_project,
            'name': 'base',
        })
        layout.addJob(base)

        other_project = model.Project('other_project')
        base2 = configloader.JobParser.fromYaml(layout, {
            '_source_project': other_project,
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
