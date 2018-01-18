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
from zuul.lib import encryption
from zuul.lib import yamlutil as yaml

from tests.base import BaseTestCase, FIXTURE_DIR


class Dummy(object):
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestJob(BaseTestCase):
    def setUp(self):
        super(TestJob, self).setUp()
        self.connection = Dummy(connection_name='dummy_connection')
        self.source = Dummy(canonical_hostname='git.example.com',
                            connection=self.connection)
        self.tenant = model.Tenant('tenant')
        self.layout = model.Layout(self.tenant)
        self.project = model.Project('project', self.source)
        self.tpc = model.TenantProjectConfig(self.project)
        self.tenant.addUntrustedProject(self.tpc)
        self.pipeline = model.Pipeline('gate', self.layout)
        self.layout.addPipeline(self.pipeline)
        self.queue = model.ChangeQueue(self.pipeline)

        private_key_file = os.path.join(FIXTURE_DIR, 'private.pem')
        with open(private_key_file, "rb") as f:
            self.project.private_key, self.project.public_key = \
                encryption.deserialize_rsa_keypair(f.read())
        self.context = model.SourceContext(self.project, 'master',
                                           'test', True)
        self.untrusted_context = model.SourceContext(self.project, 'master',
                                                     'test', False)
        m = yaml.Mark('name', 0, 0, 0, '', 0)
        self.start_mark = configloader.ZuulMark(m, m, '')

    @property
    def job(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout(tenant)
        job = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'job',
            'parent': None,
            'irrelevant-files': [
                '^docs/.*$'
            ]})
        return job

    def test_change_matches_returns_false_for_matched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'docs/foo']
        self.assertFalse(self.job.changeMatches(change))

    def test_change_matches_returns_false_for_single_matched_skip_if(self):
        change = model.Change('project')
        change.files = ['docs/foo']
        self.assertFalse(self.job.changeMatches(change))

    def test_change_matches_returns_true_for_unmatched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'foo']
        self.assertTrue(self.job.changeMatches(change))

    def test_change_matches_returns_true_for_single_unmatched_skip_if(self):
        change = model.Change('project')
        change.files = ['foo']
        self.assertTrue(self.job.changeMatches(change))

    def test_job_sets_defaults_for_boolean_attributes(self):
        self.assertIsNotNone(self.job.voting)

    def test_job_variants(self):
        # This simulates freezing a job.

        secrets = ['foo']
        py27_pre = model.PlaybookContext(self.context, 'py27-pre', [], secrets)
        py27_run = model.PlaybookContext(self.context, 'py27-run', [], secrets)
        py27_post = model.PlaybookContext(self.context, 'py27-post', [],
                                          secrets)

        py27 = model.Job('py27')
        py27.timeout = 30
        py27.pre_run = [py27_pre]
        py27.run = [py27_run]
        py27.post_run = [py27_post]

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
        self.assertEqual(secrets, job.pre_run[0].secrets)
        self.assertEqual(secrets, job.run[0].secrets)
        self.assertEqual(secrets, job.post_run[0].secrets)

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

    def test_job_inheritance_job_tree(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout(tenant)

        tpc = model.TenantProjectConfig(self.project)
        tenant.addUntrustedProject(tpc)

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'base',
            'parent': None,
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
        })
        layout.addJob(python27)
        python27diablo = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'python27',
            'branches': [
                'stable/diablo'
            ],
            'timeout': 50,
        })
        layout.addJob(python27diablo)

        project_template_parser = configloader.ProjectTemplateParser(
            tenant, layout)
        project_parser = configloader.ProjectParser(
            tenant, layout, project_template_parser)
        project_config = project_parser.fromYaml([{
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'project',
            'gate': {
                'jobs': [
                    {'python27': {'timeout': 70,
                                  'run': 'playbooks/python27.yaml'}}
                ]
            }
        }])
        layout.addProjectConfig(project_config)

        change = model.Change(self.project)
        change.branch = 'master'
        item = queue.enqueueChange(change)
        item.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertFalse(python27diablo.changeMatches(change))

        item.freezeJobGraph()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 70)

        change.branch = 'stable/diablo'
        item = queue.enqueueChange(change)
        item.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertTrue(python27.changeMatches(change))
        self.assertTrue(python27diablo.changeMatches(change))

        item.freezeJobGraph()
        self.assertEqual(len(item.getJobs()), 1)
        job = item.getJobs()[0]
        self.assertEqual(job.name, 'python27')
        self.assertEqual(job.timeout, 70)

    def test_inheritance_keeps_matchers(self):
        tenant = model.Tenant('tenant')
        layout = model.Layout(tenant)

        pipeline = model.Pipeline('gate', layout)
        layout.addPipeline(pipeline)
        queue = model.ChangeQueue(pipeline)
        project = model.Project('project', self.source)
        tpc = model.TenantProjectConfig(project)
        tenant.addUntrustedProject(tpc)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'base',
            'parent': None,
            'timeout': 30,
        })
        layout.addJob(base)
        python27 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'python27',
            'parent': 'base',
            'timeout': 40,
            'irrelevant-files': ['^ignored-file$'],
        })
        layout.addJob(python27)

        project_template_parser = configloader.ProjectTemplateParser(
            tenant, layout)
        project_parser = configloader.ProjectParser(
            tenant, layout, project_template_parser)
        project_config = project_parser.fromYaml([{
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'project',
            'gate': {
                'jobs': [
                    'python27',
                ]
            }
        }])
        layout.addProjectConfig(project_config)

        change = model.Change(project)
        change.branch = 'master'
        change.files = ['/COMMIT_MSG', 'ignored-file']
        item = queue.enqueueChange(change)
        item.layout = layout

        self.assertTrue(base.changeMatches(change))
        self.assertFalse(python27.changeMatches(change))

        item.freezeJobGraph()
        self.assertEqual([], item.getJobs())

    def test_job_source_project(self):
        tenant = self.tenant
        layout = self.layout
        base_project = model.Project('base_project', self.source)
        base_context = model.SourceContext(base_project, 'master',
                                           'test', True)
        tpc = model.TenantProjectConfig(base_project)
        tenant.addUntrustedProject(tpc)

        base = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': base_context,
            '_start_mark': self.start_mark,
            'parent': None,
            'name': 'base',
        })
        layout.addJob(base)

        other_project = model.Project('other_project', self.source)
        other_context = model.SourceContext(other_project, 'master',
                                            'test', True)
        tpc = model.TenantProjectConfig(other_project)
        tenant.addUntrustedProject(tpc)
        base2 = configloader.JobParser.fromYaml(tenant, layout, {
            '_source_context': other_context,
            '_start_mark': self.start_mark,
            'name': 'base',
        })
        with testtools.ExpectedException(
                Exception,
                "Job base in other_project is not permitted "
                "to shadow job base in base_project"):
            layout.addJob(base2)

    def test_job_allowed_projects(self):
        job = configloader.JobParser.fromYaml(self.tenant, self.layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'job',
            'parent': None,
            'allowed-projects': ['project'],
        })
        self.layout.addJob(job)

        project2 = model.Project('project2', self.source)
        tpc2 = model.TenantProjectConfig(project2)
        self.tenant.addUntrustedProject(tpc2)
        context2 = model.SourceContext(project2, 'master',
                                       'test', True)

        project_template_parser = configloader.ProjectTemplateParser(
            self.tenant, self.layout)
        project_parser = configloader.ProjectParser(
            self.tenant, self.layout, project_template_parser)
        project2_config = project_parser.fromYaml(
            [{
                '_source_context': context2,
                '_start_mark': self.start_mark,
                'name': 'project2',
                'gate': {
                    'jobs': [
                        'job'
                    ]
                }
            }]
        )
        self.layout.addProjectConfig(project2_config)

        change = model.Change(project2)
        # Test master
        change.branch = 'master'
        item = self.queue.enqueueChange(change)
        item.layout = self.layout
        with testtools.ExpectedException(
                Exception,
                "Project project2 is not allowed to run job job"):
            item.freezeJobGraph()

    def test_job_pipeline_allow_untrusted_secrets(self):
        self.pipeline.post_review = False
        job = configloader.JobParser.fromYaml(self.tenant, self.layout, {
            '_source_context': self.context,
            '_start_mark': self.start_mark,
            'name': 'job',
            'parent': None,
        })
        job.post_review = True

        self.layout.addJob(job)

        project_template_parser = configloader.ProjectTemplateParser(
            self.tenant, self.layout)
        project_parser = configloader.ProjectParser(
            self.tenant, self.layout, project_template_parser)
        project_config = project_parser.fromYaml(
            [{
                '_source_context': self.context,
                '_start_mark': self.start_mark,
                'name': 'project',
                'gate': {
                    'jobs': [
                        'job'
                    ]
                }
            }]
        )
        self.layout.addProjectConfig(project_config)

        change = model.Change(self.project)
        # Test master
        change.branch = 'master'
        item = self.queue.enqueueChange(change)
        item.layout = self.layout
        with testtools.ExpectedException(
                Exception,
                "Pre-review pipeline gate does not allow post-review job"):
            item.freezeJobGraph()


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
        pipeline = Dummy(layout=Dummy(tenant=Dummy(name='test-tenant')))
        change = Dummy(project=Dummy(canonical_name='git.example.com/foo/bar'))
        job = Dummy(name='job-name')
        item = Dummy(pipeline=pipeline,
                     change=change)
        build = Dummy(build_set=Dummy(item=item),
                      job=job)

        self.assertEqual(self.db.getEstimatedTime(build), 0)
        self.db.update(build, 50, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime(build), 50)
        self.db.update(build, 100, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime(build), 75)
        for x in range(10):
            self.db.update(build, 100, 'SUCCESS')
        self.assertEqual(self.db.getEstimatedTime(build), 100)


class TestGraph(BaseTestCase):
    def test_job_graph_disallows_multiple_jobs_with_same_name(self):
        graph = model.JobGraph()
        job1 = model.Job('job')
        job2 = model.Job('job')
        graph.addJob(job1)
        with testtools.ExpectedException(Exception,
                                         "Job job already added"):
            graph.addJob(job2)

    def test_job_graph_disallows_circular_dependencies(self):
        graph = model.JobGraph()
        jobs = [model.Job('job%d' % i) for i in range(0, 10)]
        prevjob = None
        for j in jobs[:3]:
            if prevjob:
                j.dependencies = frozenset([prevjob.name])
            graph.addJob(j)
            prevjob = j
        # 0 triggers 1 triggers 2 triggers 3...

        # Cannot depend on itself
        with testtools.ExpectedException(
                Exception,
                "Dependency cycle detected in job jobX"):
            j = model.Job('jobX')
            j.dependencies = frozenset([j.name])
            graph.addJob(j)

        # Disallow circular dependencies
        with testtools.ExpectedException(
                Exception,
                "Dependency cycle detected in job job3"):
            jobs[4].dependencies = frozenset([jobs[3].name])
            graph.addJob(jobs[4])
            jobs[3].dependencies = frozenset([jobs[4].name])
            graph.addJob(jobs[3])

        jobs[5].dependencies = frozenset([jobs[4].name])
        graph.addJob(jobs[5])

        with testtools.ExpectedException(
                Exception,
                "Dependency cycle detected in job job3"):
            jobs[3].dependencies = frozenset([jobs[5].name])
            graph.addJob(jobs[3])

        jobs[3].dependencies = frozenset([jobs[2].name])
        graph.addJob(jobs[3])
        jobs[6].dependencies = frozenset([jobs[2].name])
        graph.addJob(jobs[6])


class TestTenant(BaseTestCase):
    def test_add_project(self):
        tenant = model.Tenant('tenant')
        connection1 = Dummy(connection_name='dummy_connection1')
        source1 = Dummy(canonical_hostname='git1.example.com',
                        name='dummy',  # TODOv3(jeblair): remove
                        connection=connection1)

        source1_project1 = model.Project('project1', source1)
        source1_project1_tpc = model.TenantProjectConfig(source1_project1)
        tenant.addConfigProject(source1_project1_tpc)
        d = {'project1':
             {'git1.example.com': source1_project1}}
        self.assertEqual(d, tenant.projects)
        self.assertEqual((True, source1_project1),
                         tenant.getProject('project1'))
        self.assertEqual((True, source1_project1),
                         tenant.getProject('git1.example.com/project1'))

        source1_project2 = model.Project('project2', source1)
        tpc = model.TenantProjectConfig(source1_project2)
        tenant.addUntrustedProject(tpc)
        d = {'project1':
             {'git1.example.com': source1_project1},
             'project2':
             {'git1.example.com': source1_project2}}
        self.assertEqual(d, tenant.projects)
        self.assertEqual((False, source1_project2),
                         tenant.getProject('project2'))
        self.assertEqual((False, source1_project2),
                         tenant.getProject('git1.example.com/project2'))

        connection2 = Dummy(connection_name='dummy_connection2')
        source2 = Dummy(canonical_hostname='git2.example.com',
                        name='dummy',  # TODOv3(jeblair): remove
                        connection=connection2)

        source2_project1 = model.Project('project1', source2)
        tpc = model.TenantProjectConfig(source2_project1)
        tenant.addUntrustedProject(tpc)
        d = {'project1':
             {'git1.example.com': source1_project1,
              'git2.example.com': source2_project1},
             'project2':
             {'git1.example.com': source1_project2}}
        self.assertEqual(d, tenant.projects)
        with testtools.ExpectedException(
                Exception,
                "Project name 'project1' is ambiguous"):
            tenant.getProject('project1')
        self.assertEqual((False, source1_project2),
                         tenant.getProject('project2'))
        self.assertEqual((True, source1_project1),
                         tenant.getProject('git1.example.com/project1'))
        self.assertEqual((False, source2_project1),
                         tenant.getProject('git2.example.com/project1'))

        source2_project2 = model.Project('project2', source2)
        tpc = model.TenantProjectConfig(source2_project2)
        tenant.addConfigProject(tpc)
        d = {'project1':
             {'git1.example.com': source1_project1,
              'git2.example.com': source2_project1},
             'project2':
             {'git1.example.com': source1_project2,
              'git2.example.com': source2_project2}}
        self.assertEqual(d, tenant.projects)
        with testtools.ExpectedException(
                Exception,
                "Project name 'project1' is ambiguous"):
            tenant.getProject('project1')
        with testtools.ExpectedException(
                Exception,
                "Project name 'project2' is ambiguous"):
            tenant.getProject('project2')
        self.assertEqual((True, source1_project1),
                         tenant.getProject('git1.example.com/project1'))
        self.assertEqual((False, source2_project1),
                         tenant.getProject('git2.example.com/project1'))
        self.assertEqual((False, source1_project2),
                         tenant.getProject('git1.example.com/project2'))
        self.assertEqual((True, source2_project2),
                         tenant.getProject('git2.example.com/project2'))

        source1_project2b = model.Project('subpath/project2', source1)
        tpc = model.TenantProjectConfig(source1_project2b)
        tenant.addConfigProject(tpc)
        d = {'project1':
             {'git1.example.com': source1_project1,
              'git2.example.com': source2_project1},
             'project2':
             {'git1.example.com': source1_project2,
              'git2.example.com': source2_project2},
             'subpath/project2':
             {'git1.example.com': source1_project2b}}
        self.assertEqual(d, tenant.projects)
        self.assertEqual((False, source1_project2),
                         tenant.getProject('git1.example.com/project2'))
        self.assertEqual((True, source2_project2),
                         tenant.getProject('git2.example.com/project2'))
        self.assertEqual((True, source1_project2b),
                         tenant.getProject('subpath/project2'))
        self.assertEqual(
            (True, source1_project2b),
            tenant.getProject('git1.example.com/subpath/project2'))

        source2_project2b = model.Project('subpath/project2', source2)
        tpc = model.TenantProjectConfig(source2_project2b)
        tenant.addConfigProject(tpc)
        d = {'project1':
             {'git1.example.com': source1_project1,
              'git2.example.com': source2_project1},
             'project2':
             {'git1.example.com': source1_project2,
              'git2.example.com': source2_project2},
             'subpath/project2':
             {'git1.example.com': source1_project2b,
              'git2.example.com': source2_project2b}}
        self.assertEqual(d, tenant.projects)
        self.assertEqual((False, source1_project2),
                         tenant.getProject('git1.example.com/project2'))
        self.assertEqual((True, source2_project2),
                         tenant.getProject('git2.example.com/project2'))
        with testtools.ExpectedException(
                Exception,
                "Project name 'subpath/project2' is ambiguous"):
            tenant.getProject('subpath/project2')
        self.assertEqual(
            (True, source1_project2b),
            tenant.getProject('git1.example.com/subpath/project2'))
        self.assertEqual(
            (True, source2_project2b),
            tenant.getProject('git2.example.com/subpath/project2'))

        with testtools.ExpectedException(
                Exception,
                "Project project1 is already in project index"):
            tenant._addProject(source1_project1_tpc)
