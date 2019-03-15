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

import gc
import json
import textwrap

import os
import shutil
import socket
import time
from unittest import mock
from unittest import skip
from kazoo.exceptions import NoNodeError

import git
import testtools

import zuul.change_matcher
from zuul.driver.gerrit import gerritreporter
import zuul.scheduler
import zuul.rpcclient
import zuul.model

from tests.base import (
    SSLZuulTestCase,
    ZuulTestCase,
    repack_repo,
    simple_layout,
    iterate_timeout,
)


class TestSchedulerSSL(SSLZuulTestCase):
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


class TestSchedulerZone(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def setUp(self):
        super(TestSchedulerZone, self).setUp()
        self.fake_nodepool.attributes = {'executor-zone': 'test-provider.vpn'}

    def setup_config(self):
        super(TestSchedulerZone, self).setup_config()
        self.config.set('executor', 'zone', 'test-provider.vpn')

    def test_jobs_executed(self):
        "Test that jobs are executed and a change is merged per zone"
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        queue = self.gearman_server.getQueue()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 1)
        self.assertEqual(b'executor:execute:test-provider.vpn', queue[0].name)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
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


class TestScheduler(ZuulTestCase):
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

        # TODOv3(jeblair): we may want to report stats by tenant (also?).
        # Per-driver
        self.assertReportedStat('zuul.event.gerrit.comment-added', value='1',
                                kind='c')
        # Per-driver per-connection
        self.assertReportedStat('zuul.event.gerrit.gerrit.comment-added',
                                value='1', kind='c')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.current_changes',
            value='1', kind='g')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.project.review_example_com.'
            'org_project.master.job.project-merge.SUCCESS', kind='ms')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.project.review_example_com.'
            'org_project.master.job.project-merge.SUCCESS', value='1',
            kind='c')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.resident_time', kind='ms')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.total_changes', value='1',
            kind='c')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.project.review_example_com.'
            'org_project.master.resident_time', kind='ms')
        self.assertReportedStat(
            'zuul.tenant.tenant-one.pipeline.gate.project.review_example_com.'
            'org_project.master.total_changes', value='1', kind='c')
        exec_key = 'zuul.executor.%s' % self.executor_server.hostname.replace(
            '.', '_')
        self.assertReportedStat(exec_key + '.builds', value='1', kind='c')
        self.assertReportedStat(exec_key + '.starting_builds', kind='g')
        self.assertReportedStat(exec_key + '.starting_builds', kind='ms')
        self.assertReportedStat(
            'zuul.nodepool.requests.requested.total', value='1', kind='c')
        self.assertReportedStat(
            'zuul.nodepool.requests.requested.label.label1',
            value='1', kind='c')
        self.assertReportedStat(
            'zuul.nodepool.requests.fulfilled.label.label1',
            value='1', kind='c')
        self.assertReportedStat(
            'zuul.nodepool.requests.requested.size.1', value='1', kind='c')
        self.assertReportedStat(
            'zuul.nodepool.requests.fulfilled.size.1', value='1', kind='c')
        self.assertReportedStat(
            'zuul.nodepool.current_requests', value='1', kind='g')
        self.assertReportedStat(
            'zuul.executors.online', value='1', kind='g')
        self.assertReportedStat(
            'zuul.executors.accepting', value='1', kind='g')
        self.assertReportedStat(
            'zuul.mergers.online', value='1', kind='g')

        for build in self.history:
            self.assertTrue(build.parameters['zuul']['voting'])

    def test_initial_pipeline_gauges(self):
        "Test that each pipeline reported its length on start"
        self.assertReportedStat('zuul.tenant.tenant-one.pipeline.gate.'
                                'current_changes',
                                value='0', kind='g')
        self.assertReportedStat('zuul.tenant.tenant-one.pipeline.check.'
                                'current_changes',
                                value='0', kind='g')

    def test_job_branch(self):
        "Test the correct variant of a job runs on a branch"
        self.create_branch('org/project', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable'))
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange('org/project', 'stable', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('gate', A.messages[1],
                      "A should transit gate")
        self.assertEqual(self.getJobFromHistory('project-test1').node,
                         'label2')

    @simple_layout('layouts/branch-deletion.yaml')
    def test_branch_deletion(self):
        "Test the correct variant of a job runs on a branch"
        self._startMerger()
        for f in list(self.executor_server.merger_worker.functions.keys()):
            f = f.decode('utf8')
            if f.startswith('merger:'):
                self.executor_server.merger_worker.unRegisterFunction(f)

        self.create_branch('org/project', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable'))
        self.waitUntilSettled()
        A = self.fake_gerrit.addFakeChange('org/project', 'stable', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

        self.delete_branch('org/project', 'stable')
        path = os.path.join(self.executor_src_root, 'review.example.com')
        shutil.rmtree(path)

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        build = self.builds[0]

        # Make sure there is no stable branch in the checked out git repo.
        pname = 'review.example.com/org/project'
        work = build.getWorkspaceRepos([pname])
        work = work[pname]
        heads = set([str(x) for x in work.heads])
        self.assertEqual(heads, set(['master']))
        self.executor_server.hold_jobs_in_build = False
        build.release()
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')

    def test_parallel_changes(self):
        "Test that changes are tested in parallel and merged in series"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.builds[0].hasChanges(A))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))
        self.assertEqual(self.builds[2].name, 'project-merge')
        self.assertTrue(self.builds[2].hasChanges(A, B))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.builds[2].hasChanges(A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.builds[3].hasChanges(A, B))

        self.assertEqual(self.builds[4].name, 'project-merge')
        self.assertTrue(self.builds[4].hasChanges(A, B, C))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.builds[2].hasChanges(A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.builds[3].hasChanges(A, B))

        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertTrue(self.builds[4].hasChanges(A, B, C))
        self.assertEqual(self.builds[5].name, 'project-test2')
        self.assertTrue(self.builds[5].hasChanges(A, B, C))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(len(self.history), 9)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_changes(self):
        "Test that a change behind a failed change is retested"
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertBuilds([dict(name='project-merge', changes='1,1')])

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        # A/project-merge is complete
        self.assertBuilds([
            dict(name='project-test1', changes='1,1'),
            dict(name='project-test2', changes='1,1'),
            dict(name='project-merge', changes='1,1 2,1'),
        ])

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        # A/project-merge is complete
        # B/project-merge is complete
        self.assertBuilds([
            dict(name='project-test1', changes='1,1'),
            dict(name='project-test2', changes='1,1'),
            dict(name='project-test1', changes='1,1 2,1'),
            dict(name='project-test2', changes='1,1 2,1'),
        ])

        # Release project-test1 for A which will fail.  This will
        # abort both running B jobs and reexecute project-merge for B.
        self.builds[0].release()
        self.waitUntilSettled()

        self.orderedRelease()
        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1'),
            dict(name='project-merge', result='SUCCESS', changes='1,1 2,1'),
            dict(name='project-test1', result='FAILURE', changes='1,1'),
            dict(name='project-test1', result='ABORTED', changes='1,1 2,1'),
            dict(name='project-test2', result='ABORTED', changes='1,1 2,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-merge', result='SUCCESS', changes='2,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1'),
        ], ordered=False)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

    def test_independent_queues(self):
        "Test that changes end up in the right queues"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        # There should be one merge job at the head of each queue running
        self.assertBuilds([
            dict(name='project-merge', changes='1,1'),
            dict(name='project-merge', changes='2,1'),
        ])

        # Release the current merge builds
        self.builds[0].release()
        self.waitUntilSettled()
        self.builds[0].release()
        self.waitUntilSettled()
        # Release the merge job for project2 which is behind project1
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # All the test builds should be running:
        self.assertBuilds([
            dict(name='project-test1', changes='1,1'),
            dict(name='project-test2', changes='1,1'),
            dict(name='project-test1', changes='2,1'),
            dict(name='project-test2', changes='2,1'),
            dict(name='project1-project2-integration', changes='2,1'),
            dict(name='project-test1', changes='2,1 3,1'),
            dict(name='project-test2', changes='2,1 3,1'),
            dict(name='project1-project2-integration', changes='2,1 3,1'),
        ])

        self.orderedRelease()
        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1'),
            dict(name='project-merge', result='SUCCESS', changes='2,1'),
            dict(name='project-merge', result='SUCCESS', changes='2,1 3,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1'),
            dict(
                name='project1-project2-integration',
                result='SUCCESS',
                changes='2,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1 3,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1 3,1'),
            dict(name='project1-project2-integration',
                 result='SUCCESS',
                 changes='2,1 3,1'),
        ])

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_at_head(self):
        "Test that if a change at the head fails, jobs behind it are canceled"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='project-merge', changes='1,1'),
        ])

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='project-test1', changes='1,1'),
            dict(name='project-test2', changes='1,1'),
            dict(name='project-test1', changes='1,1 2,1'),
            dict(name='project-test2', changes='1,1 2,1'),
            dict(name='project-test1', changes='1,1 2,1 3,1'),
            dict(name='project-test2', changes='1,1 2,1 3,1'),
        ])

        self.release(self.builds[0])
        self.waitUntilSettled()

        # project-test2, project-merge for B
        self.assertBuilds([
            dict(name='project-test2', changes='1,1'),
            dict(name='project-merge', changes='2,1'),
        ])
        # Unordered history comparison because the aborts can finish
        # in any order.
        self.assertHistory([
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1 2,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1 2,1 3,1'),
            dict(name='project-test1', result='FAILURE',
                 changes='1,1'),
            dict(name='project-test1', result='ABORTED',
                 changes='1,1 2,1'),
            dict(name='project-test2', result='ABORTED',
                 changes='1,1 2,1'),
            dict(name='project-test1', result='ABORTED',
                 changes='1,1 2,1 3,1'),
            dict(name='project-test2', result='ABORTED',
                 changes='1,1 2,1 3,1'),
        ], ordered=False)

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.orderedRelease()

        self.assertBuilds([])
        self.assertHistory([
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1 2,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='1,1 2,1 3,1'),
            dict(name='project-test1', result='FAILURE',
                 changes='1,1'),
            dict(name='project-test1', result='ABORTED',
                 changes='1,1 2,1'),
            dict(name='project-test2', result='ABORTED',
                 changes='1,1 2,1'),
            dict(name='project-test1', result='ABORTED',
                 changes='1,1 2,1 3,1'),
            dict(name='project-test2', result='ABORTED',
                 changes='1,1 2,1 3,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='2,1'),
            dict(name='project-merge', result='SUCCESS',
                 changes='2,1 3,1'),
            dict(name='project-test2', result='SUCCESS',
                 changes='1,1'),
            dict(name='project-test1', result='SUCCESS',
                 changes='2,1'),
            dict(name='project-test2', result='SUCCESS',
                 changes='2,1'),
            dict(name='project-test1', result='SUCCESS',
                 changes='2,1 3,1'),
            dict(name='project-test2', result='SUCCESS',
                 changes='2,1 3,1'),
        ], ordered=False)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_in_middle(self):
        "Test a failed change in the middle of the queue"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.release(self.builds[2])
        self.waitUntilSettled()

        # project-test1 and project-test2 for A
        # project-test2 for B
        # project-merge for C (without B)
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 2)

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # project-test1 and project-test2 for A
        # project-test2 for B
        # project-test1 and project-test2 for C
        self.assertEqual(len(self.builds), 5)

        tenant = self.sched.abide.tenants.get('tenant-one')
        items = tenant.layout.pipelines['gate'].getAllItems()
        builds = items[0].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, None), 2)
        builds = items[1].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, 'FAILURE'), 1)
        self.assertEqual(self.countJobResults(builds, None), 1)
        builds = items[2].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, None), 2)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 12)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_at_head_with_queue(self):
        "Test that if a change at the head fails, queued jobs are canceled"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].name, b'executor:execute')
        job_args = json.loads(queue[0].arguments.decode('utf8'))
        self.assertEqual(job_args['job'], 'project-merge')
        self.assertEqual(job_args['items'][0]['number'], '%d' % A.number)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 6)

        self.assertEqual(
            json.loads(queue[0].arguments.decode('utf8'))['job'],
            'project-test1')
        self.assertEqual(
            json.loads(queue[1].arguments.decode('utf8'))['job'],
            'project-test2')
        self.assertEqual(
            json.loads(queue[2].arguments.decode('utf8'))['job'],
            'project-test1')
        self.assertEqual(
            json.loads(queue[3].arguments.decode('utf8'))['job'],
            'project-test2')
        self.assertEqual(
            json.loads(queue[4].arguments.decode('utf8'))['job'],
            'project-test1')
        self.assertEqual(
            json.loads(queue[5].arguments.decode('utf8'))['job'],
            'project-test2')

        self.release(queue[0])
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        queue = self.gearman_server.getQueue()
        self.assertEqual(len(queue), 2)  # project-test2, project-merge for B
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 0)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 11)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def _test_time_database(self, iteration):
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        time.sleep(2)

        data = json.loads(self.sched.formatStatusJSON('tenant-one'))
        found_job = None
        for pipeline in data['pipelines']:
            if pipeline['name'] != 'gate':
                continue
            for queue in pipeline['change_queues']:
                for head in queue['heads']:
                    for item in head:
                        for job in item['jobs']:
                            if job['name'] == 'project-merge':
                                found_job = job
                                break

        self.assertIsNotNone(found_job)
        if iteration == 1:
            self.assertIsNotNone(found_job['estimated_time'])
            self.assertIsNone(found_job['remaining_time'])
        else:
            self.assertIsNotNone(found_job['estimated_time'])
            self.assertTrue(found_job['estimated_time'] >= 2)
            self.assertIsNotNone(found_job['remaining_time'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_time_database(self):
        "Test the time database"

        self._test_time_database(1)
        self._test_time_database(2)

    def test_two_failed_changes_at_head(self):
        "Test that changes are reparented correctly if 2 fail at head"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', A)
        self.executor_server.failJob('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertTrue(self.builds[2].hasChanges(A))
        self.assertTrue(self.builds[2].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(A))
        self.assertTrue(self.builds[4].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(C))

        # Fail change B first
        self.release(self.builds[2])
        self.waitUntilSettled()

        # restart of C after B failure
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test2')
        self.assertEqual(self.builds[3].name, 'project-test1')
        self.assertEqual(self.builds[4].name, 'project-test2')

        self.assertTrue(self.builds[1].hasChanges(A))
        self.assertTrue(self.builds[2].hasChanges(A))
        self.assertTrue(self.builds[2].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(A))
        self.assertFalse(self.builds[4].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(C))

        # Finish running all passing jobs for change A
        self.release(self.builds[1])
        self.waitUntilSettled()
        # Fail and report change A
        self.release(self.builds[0])
        self.waitUntilSettled()

        # restart of B,C after A failure
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')  # B
        self.assertEqual(self.builds[1].name, 'project-test2')  # B
        self.assertEqual(self.builds[2].name, 'project-test1')  # C
        self.assertEqual(self.builds[3].name, 'project-test2')  # C

        self.assertFalse(self.builds[1].hasChanges(A))
        self.assertTrue(self.builds[1].hasChanges(B))
        self.assertFalse(self.builds[1].hasChanges(C))

        self.assertFalse(self.builds[2].hasChanges(A))
        # After A failed and B and C restarted, B should be back in
        # C's tests because it has not failed yet.
        self.assertTrue(self.builds[2].hasChanges(B))
        self.assertTrue(self.builds[2].hasChanges(C))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 21)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_patch_order(self):
        "Test that dependent patches are tested in the right order"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        M2 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M2')
        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M2.setMerged()
        M1.setMerged()

        # C -> B -> A -> M1 -> M2
        # M2 is here to make sure it is never queried.  If it is, it
        # means zuul is walking down the entire history of merged
        # changes.

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)
        M1.setDependsOn(M2, 1)

        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')

        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.assertEqual(M2.queried, 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_needed_changes_enqueue(self):
        "Test that a needed change is enqueued ahead"
        #          A      Given a git tree like this, if we enqueue
        #         / \     change C, we should walk up and down the tree
        #        B   G    and enqueue changes in the order ABCDEFG.
        #       /|\       This is also the order that you would get if
        #     *C E F      you enqueued changes in the order ABCDEFG, so
        #     /           the ordering is stable across re-enqueue events.
        #    D

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        F = self.fake_gerrit.addFakeChange('org/project', 'master', 'F')
        G = self.fake_gerrit.addFakeChange('org/project', 'master', 'G')
        B.setDependsOn(A, 1)
        C.setDependsOn(B, 1)
        D.setDependsOn(C, 1)
        E.setDependsOn(B, 1)
        F.setDependsOn(B, 1)
        G.setDependsOn(A, 1)

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)
        E.addApproval('Code-Review', 2)
        F.addApproval('Code-Review', 2)
        G.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(D.data['status'], 'NEW')
        self.assertEqual(E.data['status'], 'NEW')
        self.assertEqual(F.data['status'], 'NEW')
        self.assertEqual(G.data['status'], 'NEW')

        # We're about to add approvals to changes without adding the
        # triggering events to Zuul, so that we can be sure that it is
        # enqueing the changes based on dependencies, not because of
        # triggering events.  Since it will have the changes cached
        # already (without approvals), we need to clear the cache
        # first.
        for connection in self.connections.connections.values():
            connection.maintainCache([])

        self.executor_server.hold_jobs_in_build = True
        A.addApproval('Approved', 1)
        B.addApproval('Approved', 1)
        D.addApproval('Approved', 1)
        E.addApproval('Approved', 1)
        F.addApproval('Approved', 1)
        G.addApproval('Approved', 1)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        for x in range(8):
            self.executor_server.release('.*-merge')
            self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(E.data['status'], 'MERGED')
        self.assertEqual(F.data['status'], 'MERGED')
        self.assertEqual(G.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.reported, 2)
        self.assertEqual(E.reported, 2)
        self.assertEqual(F.reported, 2)
        self.assertEqual(G.reported, 2)
        self.assertEqual(self.history[6].changes,
                         '1,1 2,1 3,1 4,1 5,1 6,1 7,1')

    def test_source_cache(self):
        "Test that the source cache operates correctly"
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        X = self.fake_gerrit.addFakeChange('org/project', 'master', 'X')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(X.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        for build in self.builds:
            if build.pipeline == 'check':
                build.release()
        self.waitUntilSettled()
        for build in self.builds:
            if build.pipeline == 'check':
                build.release()
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.log.debug("len %s" % self.fake_gerrit._change_cache.keys())
        # there should still be changes in the cache
        self.assertNotEqual(len(self.fake_gerrit._change_cache.keys()), 0)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.queried, 2)  # Initial and isMerged
        self.assertEqual(B.queried, 3)  # Initial A, refresh from B, isMerged

    def test_can_merge(self):
        "Test whether a change is ready to merge"
        # TODO: move to test_gerrit (this is a unit test!)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        tenant = self.sched.abide.tenants.get('tenant-one')
        (trusted, project) = tenant.getProject('org/project')
        source = project.source

        # TODO(pabelanger): As we add more source / trigger APIs we should make
        # it easier for users to create events for testing.
        event = zuul.model.TriggerEvent()
        event.trigger_name = 'gerrit'
        event.change_number = '1'
        event.patch_number = '2'

        a = source.getChange(event)
        mgr = tenant.layout.pipelines['gate'].manager
        self.assertFalse(source.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('Code-Review', 2)
        a = source.getChange(event, refresh=True)
        self.assertFalse(source.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('Approved', 1)
        a = source.getChange(event, refresh=True)
        self.assertTrue(source.canMerge(a, mgr.getSubmitAllowNeeds()))

    def test_project_merge_conflict(self):
        "Test that gate merge conflicts are handled properly"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'A',
                                           files={'conflict': 'foo'})
        B = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'B',
                                           files={'conflict': 'bar'})
        C = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(C.reported, 1)

        self.gearman_server.release('project-merge')
        self.waitUntilSettled()
        self.gearman_server.release('project-merge')
        self.waitUntilSettled()
        self.gearman_server.release('project-merge')
        self.waitUntilSettled()

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertIn('Merge Failed', B.messages[-1])
        self.assertEqual(C.reported, 2)

        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-merge', result='SUCCESS', changes='1,1 3,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1 3,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1 3,1'),
        ], ordered=False)

    def test_delayed_merge_conflict(self):
        "Test that delayed check merge conflicts are handled properly"

        # Hold jobs in the gearman queue so that we can test whether
        # the executor sucesfully merges a change based on an old
        # repo state (frozen by the scheduler) which would otherwise
        # conflict.
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'A',
                                           files={'conflict': 'foo'})
        B = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'B',
                                           files={'conflict': 'bar'})
        C = self.fake_gerrit.addFakeChange('org/project',
                                           'master', 'C')
        C.setDependsOn(B, 1)

        # A enters the gate queue; B and C enter the check queue
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)  # Check does not report start
        self.assertEqual(C.reported, 0)  # Check does not report start

        # A merges while B and C are queued in check
        # Release A project-merge
        queue = self.gearman_server.getQueue()
        self.release(queue[0])
        self.waitUntilSettled()

        # Release A project-test*
        # gate has higher precedence, so A's test jobs are added in
        # front of the merge jobs for B and C
        queue = self.gearman_server.getQueue()
        self.release(queue[0])
        self.release(queue[1])
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 0)
        self.assertEqual(C.reported, 0)
        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
        ], ordered=False)

        # B and C report merge conflicts
        # Release B project-merge
        queue = self.gearman_server.getQueue()
        self.release(queue[0])
        self.waitUntilSettled()

        # Release C
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 1)

        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='project-merge', result='SUCCESS', changes='2,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1'),
            dict(name='project-merge', result='SUCCESS', changes='2,1 3,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1 3,1'),
            dict(name='project-test2', result='SUCCESS', changes='2,1 3,1'),
        ], ordered=False)

    def test_post(self):
        "Test that post jobs run"
        p = "review.example.com/org/project"
        upstream = self.getUpstreamRepos([p])
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.setMerged()
        A_commit = str(upstream[p].commit('master'))
        self.log.debug("A commit: %s" % A_commit)

        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": A_commit,
                "refName": "master",
                "project": "org/project",
            }
        }
        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 1)
        self.assertIn('project-post', job_names)

    def test_post_ignore_deletes(self):
        "Test that deleting refs does not trigger post jobs"

        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "0000000000000000000000000000000000000000",
                "refName": "master",
                "project": "org/project",
            }
        }
        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 0)
        self.assertNotIn('project-post', job_names)

    @simple_layout('layouts/dont-ignore-ref-deletes.yaml')
    def test_post_ignore_deletes_negative(self):
        "Test that deleting refs does trigger post jobs"
        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "0000000000000000000000000000000000000000",
                "refName": "testbranch",
                "project": "org/project",
            }
        }
        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 1)
        self.assertIn('project-post', job_names)

    @skip("Disabled for early v3 development")
    def test_build_configuration_branch_interaction(self):
        "Test that switching between branches works"
        self.test_build_configuration()
        self.test_build_configuration_branch()
        # C has been merged, undo that
        path = os.path.join(self.upstream_root, "org/project")
        repo = git.Repo(path)
        repo.heads.master.commit = repo.commit('init')
        self.test_build_configuration()

    def test_dependent_changes_rebase(self):
        # Test that no errors occur when we walk a dependency tree
        # with an unused leaf node due to a rebase.
        # Start by constructing: C -> B -> A
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.setDependsOn(A, 1)

        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.setDependsOn(B, 1)

        # Then rebase to form: D -> C -> A
        C.addPatchset()  # C,2
        C.setDependsOn(A, 1)

        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        D.setDependsOn(C, 2)

        # Walk the entire tree
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 3)

        # Verify that walking just part of the tree still works
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 6)

    def test_dependent_changes_dequeue(self):
        "Test that dependent patches are not needlessly tested"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        # C -> B -> A -> M1

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.executor_server.failJob('project-merge', A)

        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertIn('This change depends on a change that failed to merge.',
                      C.messages[-1])
        self.assertEqual(len(self.history), 1)

    def test_failing_dependent_changes(self):
        "Test that failing dependent patches are taken out of stream"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)
        E.addApproval('Code-Review', 2)

        # E, D -> C -> B, A

        D.setDependsOn(C, 1)
        C.setDependsOn(B, 1)

        self.executor_server.failJob('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(E.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        for build in self.builds:
            if build.parameters['zuul']['change'] != '1':
                build.release()
                self.waitUntilSettled()

        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertIn('Build succeeded', A.messages[1])
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertIn('Build failed', B.messages[1])
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertIn('depends on a change', C.messages[1])
        self.assertEqual(D.data['status'], 'NEW')
        self.assertEqual(D.reported, 2)
        self.assertIn('depends on a change', D.messages[1])
        self.assertEqual(E.data['status'], 'MERGED')
        self.assertEqual(E.reported, 2)
        self.assertIn('Build succeeded', E.messages[1])
        self.assertEqual(len(self.history), 18)

    def test_head_is_dequeued_once(self):
        "Test that if a change at the head fails it is dequeued only once"
        # If it's dequeued more than once, we should see extra
        # aborted jobs.

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.executor_server.failJob('project-test1', A)
        self.executor_server.failJob('project-test2', A)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.builds[0].hasChanges(A))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.release(self.builds[0])
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)  # test2, merge for B
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 4)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 15)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    @simple_layout('layouts/nonvoting-job-approval.yaml')
    def test_nonvoting_job_approval(self):
        "Test that non-voting jobs don't vote but leave approval"

        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.executor_server.failJob('nonvoting-project-test2', A)

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)

        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test1').result,
            'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test2').result,
            'FAILURE')

        self.assertFalse(self.getJobFromHistory('nonvoting-project-test1').
                         parameters['zuul']['voting'])
        self.assertFalse(self.getJobFromHistory('nonvoting-project-test2').
                         parameters['zuul']['voting'])
        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "1")

    @simple_layout('layouts/nonvoting-job.yaml')
    def test_nonvoting_job(self):
        "Test that non-voting jobs don't vote."

        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        A.addApproval('Code-Review', 2)
        self.executor_server.failJob('nonvoting-project-test2', A)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-merge').result,
            'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test1').result,
            'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test2').result,
            'FAILURE')

        self.assertTrue(self.getJobFromHistory('nonvoting-project-merge').
                        parameters['zuul']['voting'])
        self.assertTrue(self.getJobFromHistory('nonvoting-project-test1').
                        parameters['zuul']['voting'])
        self.assertFalse(self.getJobFromHistory('nonvoting-project-test2').
                         parameters['zuul']['voting'])

    def test_check_queue_success(self):
        "Test successful check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

    def test_check_queue_failure(self):
        "Test failed check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.executor_server.failJob('project-test2', A)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'FAILURE')

    @simple_layout('layouts/autohold.yaml')
    def test_autohold(self):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.autohold('tenant-one', 'org/project', 'project-test2',
                            "", "", "reason text", 1)
        self.assertTrue(r)

        # First check that successful jobs do not autohold
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        # project-test2
        self.assertEqual(self.history[0].result, 'SUCCESS')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNone(held_node)

        # Now test that failed jobs are autoheld
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.executor_server.failJob('project-test2', B)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        # project-test2
        self.assertEqual(self.history[1].result, 'FAILURE')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNotNone(held_node)

        # Validate node has recorded the failed job
        self.assertEqual(
            held_node['hold_job'],
            " ".join(['tenant-one',
                      'review.example.com/org/project',
                      'project-test2', '.*'])
        )
        self.assertEqual(held_node['comment'], "reason text")

        # Another failed change should not hold any more nodes
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        self.executor_server.failJob('project-test2', C)
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 1)
        # project-test2
        self.assertEqual(self.history[2].result, 'FAILURE')

        held_nodes = 0
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_nodes += 1
        self.assertEqual(held_nodes, 1)

    def _test_autohold_scoped(self, change_obj, change, ref):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        # create two changes on the same project, and autohold request
        # for one of them.
        other = self.fake_gerrit.addFakeChange(
            'org/project', 'master', 'other'
        )

        r = client.autohold('tenant-one', 'org/project', 'project-test2',
                            str(change), ref, "reason text", 1)
        self.assertTrue(r)

        # First, check that an unrelated job does not trigger autohold, even
        # when it failed
        self.executor_server.failJob('project-test2', other)
        self.fake_gerrit.addEvent(other.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(other.data['status'], 'NEW')
        self.assertEqual(other.reported, 1)
        # project-test2
        self.assertEqual(self.history[0].result, 'FAILURE')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNone(held_node)

        # And then verify that failed job for the defined change
        # triggers the autohold

        self.executor_server.failJob('project-test2', change_obj)
        self.fake_gerrit.addEvent(change_obj.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(change_obj.data['status'], 'NEW')
        self.assertEqual(change_obj.reported, 1)
        # project-test2
        self.assertEqual(self.history[1].result, 'FAILURE')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNotNone(held_node)

        # Validate node has recorded the failed job
        if change != "":
            ref = "refs/changes/%s/%s/.*" % (
                str(change_obj.number)[-1:], str(change_obj.number)
            )

        self.assertEqual(
            held_node['hold_job'],
            " ".join(['tenant-one',
                      'review.example.com/org/project',
                      'project-test2', ref])
        )
        self.assertEqual(held_node['comment'], "reason text")

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_change(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')

        self._test_autohold_scoped(A, change=A.number, ref="")

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_ref(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        ref = A.data['currentPatchSet']['ref']
        self._test_autohold_scoped(A, change="", ref=ref)

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_scoping(self):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')

        # create three autohold requests, scoped to job, change and
        # a specific ref
        change = str(A.number)
        ref = A.data['currentPatchSet']['ref']
        r1 = client.autohold('tenant-one', 'org/project', 'project-test2',
                             "", "", "reason text", 1)
        self.assertTrue(r1)
        r2 = client.autohold('tenant-one', 'org/project', 'project-test2',
                             change, "", "reason text", 1)
        self.assertTrue(r2)
        r3 = client.autohold('tenant-one', 'org/project', 'project-test2',
                             "", ref, "reason text", 1)
        self.assertTrue(r3)

        # Fail 3 jobs for the same change, and verify that the autohold
        # requests are fullfilled in the expected order: from the most
        # specific towards the most generic one.

        def _fail_job_and_verify_autohold_request(change_obj, ref_filter):
            self.executor_server.failJob('project-test2', change_obj)
            self.fake_gerrit.addEvent(change_obj.getPatchsetCreatedEvent(1))

            self.waitUntilSettled()

            # Check nodepool for a held node
            held_node = None
            for node in self.fake_nodepool.getNodes():
                if node['state'] == zuul.model.STATE_HOLD:
                    held_node = node
                    break
            self.assertIsNotNone(held_node)

            self.assertEqual(
                held_node['hold_job'],
                " ".join(['tenant-one',
                          'review.example.com/org/project',
                          'project-test2', ref_filter])
            )
            self.assertFalse(held_node['_lock'], "Node %s is locked" %
                             (node['_oid'],))
            self.fake_nodepool.removeNode(held_node)

        _fail_job_and_verify_autohold_request(A, ref)

        ref = "refs/changes/%s/%s/.*" % (str(change)[-1:], str(change))
        _fail_job_and_verify_autohold_request(A, ref)
        _fail_job_and_verify_autohold_request(A, ".*")

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_ignores_aborted_jobs(self):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.autohold('tenant-one', 'org/project', 'project-test2',
                            "", "", "reason text", 1)
        self.assertTrue(r)

        self.executor_server.hold_jobs_in_build = True

        # Create a change that will have its job aborted
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Creating new patchset on change A will abort A,1's job because
        # a new patchset arrived replacing A,1 with A,2.
        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))

        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        # Note only the successful job for A,2 will report as we don't
        # report aborted builds for old patchsets.
        self.assertEqual(A.reported, 1)
        # A,1 project-test2
        self.assertEqual(self.history[0].result, 'ABORTED')
        # A,2 project-test2
        self.assertEqual(self.history[1].result, 'SUCCESS')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNone(held_node)

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_hold_expiration(self):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.autohold('tenant-one', 'org/project', 'project-test2',
                            "", "", "reason text", 1, node_hold_expiration=30)
        self.assertTrue(r)

        # Hold a failed job
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.executor_server.failJob('project-test2', B)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        # project-test2
        self.assertEqual(self.history[0].result, 'FAILURE')

        # Check nodepool for a held node
        held_node = None
        for node in self.fake_nodepool.getNodes():
            if node['state'] == zuul.model.STATE_HOLD:
                held_node = node
                break
        self.assertIsNotNone(held_node)

        # Validate node has hold_expiration property
        self.assertEqual(int(held_node['hold_expiration']), 30)

    @simple_layout('layouts/autohold.yaml')
    def test_autohold_list(self):
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        r = client.autohold('tenant-one', 'org/project', 'project-test2',
                            "", "", "reason text", 1)
        self.assertTrue(r)

        autohold_requests = client.autohold_list()
        self.assertNotEqual({}, autohold_requests)
        self.assertEqual(1, len(autohold_requests.keys()))

        # The single dict key should be a CSV string value
        key = list(autohold_requests.keys())[0]
        tenant, project, job, ref_filter = key.split(',')

        self.assertEqual('tenant-one', tenant)
        self.assertIn('org/project', project)
        self.assertEqual('project-test2', job)
        self.assertEqual(".*", ref_filter)

        # Note: the value is converted from set to list by json.
        self.assertEqual([1, "reason text", None], autohold_requests[key])

    @simple_layout('layouts/three-projects.yaml')
    def test_dependent_behind_dequeue(self):
        # This particular test does a large amount of merges and needs a little
        # more time to complete
        self.wait_timeout = 120
        "test that dependent changes behind dequeued changes work"
        # This complicated test is a reproduction of a real life bug
        self.sched.reconfigure(self.config)

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project2', 'master', 'E')
        F = self.fake_gerrit.addFakeChange('org/project3', 'master', 'F')
        D.setDependsOn(C, 1)
        E.setDependsOn(D, 1)
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)
        E.addApproval('Code-Review', 2)
        F.addApproval('Code-Review', 2)

        A.fail_merge = True

        # Change object re-use in the gerrit trigger is hidden if
        # changes are added in quick succession; waiting makes it more
        # like real life.
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(E.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(F.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # all jobs running

        # Grab pointers to the jobs we want to release before
        # releasing any, because list indexes may change as
        # the jobs complete.
        a, b, c = self.builds[:3]
        a.release()
        b.release()
        c.release()
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(E.data['status'], 'MERGED')
        self.assertEqual(F.data['status'], 'MERGED')

        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.reported, 2)
        self.assertEqual(E.reported, 2)
        self.assertEqual(F.reported, 2)

        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 15)
        self.assertEqual(len(self.history), 44)

    def test_merger_repack(self):
        "Test that the merger works after a repack"

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
        self.assertEmptyQueues()
        self.build_history = []

        path = os.path.join(self.merger_src_root, "review.example.com",
                            "org/project")
        if os.path.exists(path):
            repack_repo(path)
        path = os.path.join(self.executor_src_root, "review.example.com",
                            "org/project")
        if os.path.exists(path):
            repack_repo(path)

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

    def test_merger_repack_large_change(self):
        "Test that the merger works with large changes after a repack"
        # https://bugs.executepad.net/zuul/+bug/1078946
        # This test assumes the repo is already cloned; make sure it is
        tenant = self.sched.abide.tenants.get('tenant-one')
        trusted, project = tenant.getProject('org/project')
        url = self.fake_gerrit.getGitUrl(project)
        self.executor_server.merger._addProject('review.example.com',
                                                'org/project', url, None)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset(large=True)
        # TODOv3(jeblair): add hostname to upstream root
        path = os.path.join(self.upstream_root, 'org/project')
        repack_repo(path)
        path = os.path.join(self.merger_src_root, 'review.example.com',
                            'org/project')
        if os.path.exists(path):
            repack_repo(path)
        path = os.path.join(self.executor_src_root, 'review.example.com',
                            'org/project')
        if os.path.exists(path):
            repack_repo(path)

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

    def test_new_patchset_dequeues_old(self):
        "Test that a new patchset causes the old to be dequeued"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.executor_server.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)
        self.assertEqual(len(self.history), 9)  # 3 each for A, B, D.

    def test_new_patchset_check(self):
        "Test a new patchset in check"

        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        # Add two git-dependent changes
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # A live item, and a non-live/live pair
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '1')
        self.assertFalse(items[0].live)

        self.assertEqual(items[1].change.number, '2')
        self.assertEqual(items[1].change.patchset, '1')
        self.assertTrue(items[1].live)

        self.assertEqual(items[2].change.number, '1')
        self.assertEqual(items[2].change.patchset, '1')
        self.assertTrue(items[2].live)

        # Add a new patchset to A
        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        # The live copy of A,1 should be gone, but the non-live and B
        # should continue, and we should have a new A,2
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '1')
        self.assertFalse(items[0].live)

        self.assertEqual(items[1].change.number, '2')
        self.assertEqual(items[1].change.patchset, '1')
        self.assertTrue(items[1].live)

        self.assertEqual(items[2].change.number, '1')
        self.assertEqual(items[2].change.patchset, '2')
        self.assertTrue(items[2].live)

        # Add a new patchset to B
        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        # The live copy of B,1 should be gone, and it's non-live copy of A,1
        # but we should have a new B,2 (still based on A,1)
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '2')
        self.assertTrue(items[0].live)

        self.assertEqual(items[1].change.number, '1')
        self.assertEqual(items[1].change.patchset, '1')
        self.assertFalse(items[1].live)

        self.assertEqual(items[2].change.number, '2')
        self.assertEqual(items[2].change.patchset, '2')
        self.assertTrue(items[2].live)

        self.builds[0].release()
        self.waitUntilSettled()
        self.builds[0].release()
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertEqual(self.history[0].result, 'ABORTED')
        self.assertEqual(self.history[0].changes, '1,1')
        self.assertEqual(self.history[1].result, 'ABORTED')
        self.assertEqual(self.history[1].changes, '1,1 2,1')
        self.assertEqual(self.history[2].result, 'SUCCESS')
        self.assertEqual(self.history[2].changes, '1,2')
        self.assertEqual(self.history[3].result, 'SUCCESS')
        self.assertEqual(self.history[3].changes, '1,1 2,2')

    def test_abandoned_gate(self):
        "Test that an abandoned change is dequeued from gate"

        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1, "One job being built (on hold)")
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertBuilds([])
        self.assertHistory([
            dict(name='project-merge', result='ABORTED', changes='1,1')],
            ordered=False)
        self.assertEqual(A.reported, 1,
                         "Abandoned gate change should report only start")

    def test_abandoned_check(self):
        "Test that an abandoned change is dequeued from check"

        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        # Add two git-dependent changes
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        # A live item, and a non-live/live pair
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0].change.number, '1')
        self.assertFalse(items[0].live)

        self.assertEqual(items[1].change.number, '2')
        self.assertTrue(items[1].live)

        self.assertEqual(items[2].change.number, '1')
        self.assertTrue(items[2].live)

        # Abandon A
        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        # The live copy of A should be gone, but the non-live and B
        # should continue
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 2)

        self.assertEqual(items[0].change.number, '1')
        self.assertFalse(items[0].live)

        self.assertEqual(items[1].change.number, '2')
        self.assertTrue(items[1].live)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 4)
        self.assertEqual(self.history[0].result, 'ABORTED',
                         'Build should have been aborted')
        self.assertEqual(A.reported, 0, "Abandoned change should not report")
        self.assertEqual(B.reported, 1, "Change should report")

    def test_abandoned_not_timer(self):
        "Test that an abandoned change does not cancel timer jobs"
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.executor_server.hold_jobs_in_build = True
        # Start timer trigger - also org/project
        self.commitConfigUpdate('common-config', 'layouts/idle.yaml')
        self.sched.reconfigure(self.config)
        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()
        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        # Must be in same repo, so overwrite config with another one
        self.commitConfigUpdate('common-config', 'layouts/no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1, "One timer job")

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 2, "One change plus one timer job")

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1, "One timer job remains")

        self.executor_server.release()
        self.waitUntilSettled()

    def test_new_patchset_dequeues_old_on_head(self):
        "Test that a new patchset causes the old to be dequeued (at head)"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.executor_server.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))
        self.waitUntilSettled()

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)
        self.assertEqual(len(self.history), 7)

    def test_new_patchset_dequeues_old_without_dependents(self):
        "Test that a new patchset causes only the old to be dequeued"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 9)

    def test_new_patchset_dequeues_old_independent_queue(self):
        "Test that a new patchset causes the old to be dequeued (independent)"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 1)
        self.assertEqual(len(self.history), 10)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

    @simple_layout('layouts/noop-job.yaml')
    def test_noop_job(self):
        "Test that the internal noop job works"
        A = self.fake_gerrit.addFakeChange('org/noop-project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())
        self.assertEqual(len(self.history), 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    @simple_layout('layouts/no-jobs-project.yaml')
    def test_no_job_project(self):
        "Test that reports with no jobs don't get sent"
        A = self.fake_gerrit.addFakeChange('org/no-jobs-project',
                                           'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Change wasn't reported to
        self.assertEqual(A.reported, False)

        # Check queue is empty afterwards
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        self.assertEqual(len(self.history), 0)

    def test_zuul_refs(self):
        "Test that zuul refs exist and have the right changes"
        self.executor_server.hold_jobs_in_build = True
        M1 = self.fake_gerrit.addFakeChange('org/project1', 'master', 'M1')
        M1.setMerged()
        M2 = self.fake_gerrit.addFakeChange('org/project2', 'master', 'M2')
        M2.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        a_build = b_build = c_build = d_build = None
        for x in self.builds:
            if x.parameters['zuul']['change'] == '3':
                a_build = x
            elif x.parameters['zuul']['change'] == '4':
                b_build = x
            elif x.parameters['zuul']['change'] == '5':
                c_build = x
            elif x.parameters['zuul']['change'] == '6':
                d_build = x
            if a_build and b_build and c_build and d_build:
                break

        # should have a, not b, and should not be in project2
        self.assertTrue(a_build.hasChanges(A))
        self.assertFalse(a_build.hasChanges(B, M2))

        # should have a and b, and should not be in project2
        self.assertTrue(b_build.hasChanges(A, B))
        self.assertFalse(b_build.hasChanges(M2))

        # should have a and b in 1, c in 2
        self.assertTrue(c_build.hasChanges(A, B, C))
        self.assertFalse(c_build.hasChanges(D))

        # should have a and b in 1, c and d in 2
        self.assertTrue(d_build.hasChanges(A, B, C, D))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)

    def test_rerun_on_error(self):
        "Test that if a worker fails to run a job, it is run again"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.builds[0].requeue = True
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(self.countJobResults(self.history, None), 1)
        self.assertEqual(self.countJobResults(self.history, 'SUCCESS'), 3)

    def test_statsd(self):
        "Test each of the statsd methods used in the scheduler"
        statsd = self.sched.statsd
        statsd.incr('test-incr')
        statsd.timing('test-timing', 3)
        statsd.gauge('test-gauge', 12)
        self.assertReportedStat('test-incr', '1', 'c')
        self.assertReportedStat('test-timing', '3', 'ms')
        self.assertReportedStat('test-gauge', '12', 'g')

        # test key normalization
        statsd.extra_keys = {'hostname': '1_2_3_4'}

        statsd.incr('hostname-incr.{hostname}.{fake}', fake='1:2')
        statsd.timing('hostname-timing.{hostname}.{fake}', 3, fake='1:2')
        statsd.gauge('hostname-gauge.{hostname}.{fake}', 12, fake='1:2')
        self.assertReportedStat('hostname-incr.1_2_3_4.1_2', '1', 'c')
        self.assertReportedStat('hostname-timing.1_2_3_4.1_2', '3', 'ms')
        self.assertReportedStat('hostname-gauge.1_2_3_4.1_2', '12', 'g')

    def test_statsd_conflict(self):
        statsd = self.sched.statsd
        statsd.gauge('test-gauge', 12)
        # since test-gauge is already a value, we can't make
        # subvalues.  Test the assert works.
        statsd.gauge('test-gauge.1_2_3_4', 12)
        self.assertReportedStat('test-gauge', '12', 'g')
        self.assertRaises(Exception, self.assertReportedStat,
                          'test-gauge.1_2_3_4', '12', 'g')

    def test_stuck_job_cleanup(self):
        "Test that pending jobs are cleaned up if removed from layout"

        # We want to hold the project-merge job that the fake change enqueues
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        # The assertion is that we have one job in the queue, project-merge
        self.assertEqual(len(self.gearman_server.getQueue()), 1)

        self.commitConfigUpdate('common-config', 'layouts/no-jobs.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.gearman_server.release('gate-noop')
        self.waitUntilSettled()
        # asserting that project-merge is removed from queue
        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())

        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'gate-noop')
        self.assertEqual(self.history[0].result, 'SUCCESS')

    def test_file_head(self):
        # This is a regression test for an observed bug.  A change
        # with a file named "HEAD" in the root directory of the repo
        # was processed by a merger.  It then was unable to reset the
        # repo because of:
        #   GitCommandError: 'git reset --hard HEAD' returned
        #       with exit code 128
        #   stderr: 'fatal: ambiguous argument 'HEAD': both revision
        #       and filename
        #   Use '--' to separate filenames from revisions'

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset({'HEAD': ''})
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertIn('Build succeeded', A.messages[0])
        self.assertIn('Build succeeded', B.messages[0])

    def test_file_jobs(self):
        "Test that file jobs run only when appropriate"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset({'pip-requires': 'foo'})
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        testfile_jobs = [x for x in self.history
                         if x.name == 'project-testfile']

        self.assertEqual(len(testfile_jobs), 1)
        self.assertEqual(testfile_jobs[0].changes, '1,2')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def _test_irrelevant_files_jobs(self, should_skip):
        "Test that jobs with irrelevant-files filter run only when appropriate"
        if should_skip:
            files = {'ignoreme': 'ignored\n'}
        else:
            files = {'respectme': 'please!\n'}

        change = self.fake_gerrit.addFakeChange('org/project',
                                                'master',
                                                'test irrelevant-files',
                                                files=files)
        self.fake_gerrit.addEvent(change.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        tested_change_ids = [x.changes[0] for x in self.history
                             if x.name == 'project-test-irrelevant-files']

        if should_skip:
            self.assertEqual([], tested_change_ids)
        else:
            self.assertIn(change.data['number'], tested_change_ids)

    @simple_layout('layouts/irrelevant-files.yaml')
    def test_irrelevant_files_match_skips_job(self):
        self._test_irrelevant_files_jobs(should_skip=True)

    @simple_layout('layouts/irrelevant-files.yaml')
    def test_irrelevant_files_no_match_runs_job(self):
        self._test_irrelevant_files_jobs(should_skip=False)

    @simple_layout('layouts/inheritance.yaml')
    def test_inherited_jobs_keep_matchers(self):
        files = {'ignoreme': 'ignored\n'}

        change = self.fake_gerrit.addFakeChange('org/project',
                                                'master',
                                                'test irrelevant-files',
                                                files=files)
        self.fake_gerrit.addEvent(change.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        run_jobs = set([build.name for build in self.history])

        self.assertEqual(set(['project-test-nomatch-starts-empty',
                              'project-test-nomatch-starts-full']), run_jobs)

    @simple_layout('layouts/job-vars.yaml')
    def test_inherited_job_variables(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='parentjob', result='SUCCESS'),
            dict(name='child1', result='SUCCESS'),
            dict(name='child2', result='SUCCESS'),
            dict(name='child3', result='SUCCESS'),
            dict(name='override_project_var', result='SUCCESS'),
            dict(name='job_from_template1', result='SUCCESS'),
            dict(name='job_from_template2', result='SUCCESS'),
        ], ordered=False)
        j = self.getJobFromHistory('parentjob')
        rp = set([p['name'] for p in j.parameters['projects']])
        self.assertEqual(j.parameters['vars']['project_var'], 'set_in_project')
        self.assertEqual(j.parameters['vars']['template_var1'],
                         'set_in_template1')
        self.assertEqual(j.parameters['vars']['template_var2'],
                         'set_in_template2')
        self.assertEqual(j.parameters['vars']['override'], 0)
        self.assertEqual(j.parameters['vars']['child1override'], 0)
        self.assertEqual(j.parameters['vars']['parent'], 0)
        self.assertEqual(j.parameters['vars']['deep']['override'], 0)
        self.assertFalse('child1' in j.parameters['vars'])
        self.assertFalse('child2' in j.parameters['vars'])
        self.assertFalse('child3' in j.parameters['vars'])
        self.assertEqual(rp, set(['org/project', 'org/project0',
                                  'org/project0']))
        j = self.getJobFromHistory('child1')
        rp = set([p['name'] for p in j.parameters['projects']])
        self.assertEqual(j.parameters['vars']['project_var'], 'set_in_project')
        self.assertEqual(j.parameters['vars']['override'], 1)
        self.assertEqual(j.parameters['vars']['child1override'], 1)
        self.assertEqual(j.parameters['vars']['parent'], 0)
        self.assertEqual(j.parameters['vars']['child1'], 1)
        self.assertEqual(j.parameters['vars']['deep']['override'], 1)
        self.assertFalse('child2' in j.parameters['vars'])
        self.assertFalse('child3' in j.parameters['vars'])
        self.assertEqual(rp, set(['org/project', 'org/project0',
                                  'org/project1']))
        j = self.getJobFromHistory('child2')
        self.assertEqual(j.parameters['vars']['project_var'], 'set_in_project')
        rp = set([p['name'] for p in j.parameters['projects']])
        self.assertEqual(j.parameters['vars']['override'], 2)
        self.assertEqual(j.parameters['vars']['child1override'], 0)
        self.assertEqual(j.parameters['vars']['parent'], 0)
        self.assertEqual(j.parameters['vars']['deep']['override'], 2)
        self.assertFalse('child1' in j.parameters['vars'])
        self.assertEqual(j.parameters['vars']['child2'], 2)
        self.assertFalse('child3' in j.parameters['vars'])
        self.assertEqual(rp, set(['org/project', 'org/project0',
                                  'org/project2']))
        j = self.getJobFromHistory('child3')
        self.assertEqual(j.parameters['vars']['project_var'], 'set_in_project')
        rp = set([p['name'] for p in j.parameters['projects']])
        self.assertEqual(j.parameters['vars']['override'], 3)
        self.assertEqual(j.parameters['vars']['child1override'], 0)
        self.assertEqual(j.parameters['vars']['parent'], 0)
        self.assertEqual(j.parameters['vars']['deep']['override'], 3)
        self.assertFalse('child1' in j.parameters['vars'])
        self.assertFalse('child2' in j.parameters['vars'])
        self.assertEqual(j.parameters['vars']['child3'], 3)
        self.assertEqual(rp, set(['org/project', 'org/project0',
                                  'org/project3']))
        j = self.getJobFromHistory('override_project_var')
        self.assertEqual(j.parameters['vars']['project_var'],
                         'override_in_job')

    @simple_layout('layouts/job-variants.yaml')
    def test_job_branch_variants(self):
        self.create_branch('org/project', 'stable/diablo')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable/diablo'))
        self.create_branch('org/project', 'stable/essex')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable/essex'))
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'stable/diablo', 'B')
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        C = self.fake_gerrit.addFakeChange('org/project', 'stable/essex', 'C')
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='python27', result='SUCCESS'),
            dict(name='python27', result='SUCCESS'),
            dict(name='python27', result='SUCCESS'),
        ])

        p = self.history[0].parameters
        self.assertEqual(p['timeout'], 40)
        self.assertEqual(len(p['nodes']), 1)
        self.assertEqual(p['nodes'][0]['label'], 'new')
        self.assertEqual([x['path'] for x in p['pre_playbooks']],
                         ['base-pre', 'py27-pre'])
        self.assertEqual([x['path'] for x in p['post_playbooks']],
                         ['py27-post-a', 'py27-post-b', 'base-post'])
        self.assertEqual([x['path'] for x in p['playbooks']],
                         ['playbooks/python27.yaml'])

        p = self.history[1].parameters
        self.assertEqual(p['timeout'], 50)
        self.assertEqual(len(p['nodes']), 1)
        self.assertEqual(p['nodes'][0]['label'], 'old')
        self.assertEqual([x['path'] for x in p['pre_playbooks']],
                         ['base-pre', 'py27-pre', 'py27-diablo-pre'])
        self.assertEqual([x['path'] for x in p['post_playbooks']],
                         ['py27-diablo-post', 'py27-post-a', 'py27-post-b',
                          'base-post'])
        self.assertEqual([x['path'] for x in p['playbooks']],
                         ['py27-diablo'])

        p = self.history[2].parameters
        self.assertEqual(p['timeout'], 40)
        self.assertEqual(len(p['nodes']), 1)
        self.assertEqual(p['nodes'][0]['label'], 'new')
        self.assertEqual([x['path'] for x in p['pre_playbooks']],
                         ['base-pre', 'py27-pre', 'py27-essex-pre'])
        self.assertEqual([x['path'] for x in p['post_playbooks']],
                         ['py27-essex-post', 'py27-post-a', 'py27-post-b',
                          'base-post'])
        self.assertEqual([x['path'] for x in p['playbooks']],
                         ['playbooks/python27.yaml'])

    @simple_layout("layouts/no-run.yaml")
    def test_job_without_run(self):
        "Test that a job without a run playbook errors"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertIn('Job base does not specify a run playbook',
                      A.messages[-1])

    def test_queue_names(self):
        "Test shared change queue names"
        tenant = self.sched.abide.tenants.get('tenant-one')
        (trusted, project1) = tenant.getProject('org/project1')
        (trusted, project2) = tenant.getProject('org/project2')
        q1 = tenant.layout.pipelines['gate'].getQueue(project1)
        q2 = tenant.layout.pipelines['gate'].getQueue(project2)
        self.assertEqual(q1.name, 'integrated')
        self.assertEqual(q2.name, 'integrated')

    @simple_layout("layouts/template-queue.yaml")
    def test_template_queue(self):
        "Test a shared queue can be constructed from a project-template"
        tenant = self.sched.abide.tenants.get('tenant-one')
        (trusted, project1) = tenant.getProject('org/project1')
        (trusted, project2) = tenant.getProject('org/project2')
        q1 = tenant.layout.pipelines['gate'].getQueue(project1)
        q2 = tenant.layout.pipelines['gate'].getQueue(project2)
        self.assertEqual(q1.name, 'integrated')
        self.assertEqual(q2.name, 'integrated')

    @simple_layout("layouts/regex-template-queue.yaml")
    def test_regex_template_queue(self):
        "Test a shared queue can be constructed from a regex project-template"
        tenant = self.sched.abide.tenants.get('tenant-one')
        (trusted, project1) = tenant.getProject('org/project1')
        (trusted, project2) = tenant.getProject('org/project2')
        q1 = tenant.layout.pipelines['gate'].getQueue(project1)
        q2 = tenant.layout.pipelines['gate'].getQueue(project2)
        self.assertEqual(q1.name, 'integrated')
        self.assertEqual(q2.name, 'integrated')

    @simple_layout("layouts/regex-queue.yaml")
    def test_regex_queue(self):
        "Test a shared queue can be constructed from a regex project"
        tenant = self.sched.abide.tenants.get('tenant-one')
        (trusted, project1) = tenant.getProject('org/project1')
        (trusted, project2) = tenant.getProject('org/project2')
        q1 = tenant.layout.pipelines['gate'].getQueue(project1)
        q2 = tenant.layout.pipelines['gate'].getQueue(project2)
        self.assertEqual(q1.name, 'integrated')
        self.assertEqual(q2.name, 'integrated')

    def test_queue_precedence(self):
        "Test that queue precedence works"

        self.gearman_server.hold_jobs_in_queue = True
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        # Run one build at a time to ensure non-race order:
        self.orderedRelease()
        self.executor_server.hold_jobs_in_build = False
        self.waitUntilSettled()

        self.log.debug(self.history)
        self.assertEqual(self.history[0].pipeline, 'gate')
        self.assertEqual(self.history[1].pipeline, 'check')
        self.assertEqual(self.history[2].pipeline, 'gate')
        self.assertEqual(self.history[3].pipeline, 'gate')
        self.assertEqual(self.history[4].pipeline, 'check')
        self.assertEqual(self.history[5].pipeline, 'check')

    def test_reconfigure_merge(self):
        """Test that two reconfigure events are merged"""

        tenant = self.sched.abide.tenants['tenant-one']
        (trusted, project) = tenant.getProject('org/project')

        self.sched.run_handler_lock.acquire()
        self.assertEqual(self.sched.management_event_queue.qsize(), 0)

        self.sched.reconfigureTenant(tenant, project, None)
        self.assertEqual(self.sched.management_event_queue.qsize(), 1)

        self.sched.reconfigureTenant(tenant, project, None)
        # The second event should have been combined with the first
        # so we should still only have one entry.
        self.assertEqual(self.sched.management_event_queue.qsize(), 1)

        self.sched.run_handler_lock.release()
        self.waitUntilSettled()

        self.assertEqual(self.sched.management_event_queue.qsize(), 0)

    def test_live_reconfiguration(self):
        "Test that live reconfiguration works"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_live_reconfiguration_command_socket(self):
        "Test that live reconfiguration via command socket works"

        # record previous tenant reconfiguration time, which may not be set
        old = self.sched.tenant_last_reconfigured.get('tenant-one', 0)
        time.sleep(1)
        self.waitUntilSettled()

        command_socket = self.config.get('scheduler', 'command_socket')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(command_socket)
            s.sendall('full-reconfigure\n'.encode('utf8'))

        # Wait for full reconfiguration. Note that waitUntilSettled is not
        # reliable here because the reconfigure event may arrive in the
        # event queue after waitUntilSettled.
        start = time.time()
        while True:
            if time.time() - start > 15:
                raise Exception("Timeout waiting for full reconfiguration")
            new = self.sched.tenant_last_reconfigured.get('tenant-one', 0)
            if old < new:
                break
            else:
                time.sleep(0)

    def test_live_reconfiguration_abort(self):
        # Raise an exception during reconfiguration and verify we
        # still function.
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        pipeline = tenant.layout.pipelines['gate']
        change = pipeline.getAllItems()[0].change
        # Set this to an invalid value to cause an exception during
        # reconfiguration.
        change.branch = None

        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'ABORTED')
        self.assertEqual(A.data['status'], 'NEW')
        # The final report fails because of the invalid value set above.
        self.assertEqual(A.reported, 1)

    def test_live_reconfiguration_merge_conflict(self):
        # A real-world bug: a change in a gate queue has a merge
        # conflict and a job is added to its project while it's
        # sitting in the queue.  The job gets added to the change and
        # enqueued and the change gets stuck.
        self.executor_server.hold_jobs_in_build = True

        # This change is fine.  It's here to stop the queue long
        # enough for the next change to be subject to the
        # reconfiguration, as well as to provide a conflict for the
        # next change.  This change will succeed and merge.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset({'conflict': 'A'})
        A.addApproval('Code-Review', 2)

        # This change will be in merge conflict.  During the
        # reconfiguration, we will add a job.  We want to make sure
        # that doesn't cause it to get stuck.
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset({'conflict': 'B'})
        B.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))

        self.waitUntilSettled()

        # No jobs have run yet
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(len(self.history), 0)

        # Add the "project-test3" job.
        self.commitConfigUpdate('common-config',
                                'layouts/live-reconfiguration-add-job.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertIn('Merge Failed', B.messages[-1])
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test3').result,
                         'SUCCESS')
        self.assertEqual(len(self.history), 4)

    def test_live_reconfiguration_failed_root(self):
        # An extrapolation of test_live_reconfiguration_merge_conflict
        # that tests a job added to a job tree with a failed root does
        # not run.
        self.executor_server.hold_jobs_in_build = True

        # This change is fine.  It's here to stop the queue long
        # enough for the next change to be subject to the
        # reconfiguration.  This change will succeed and merge.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset({'conflict': 'A'})
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.executor_server.failJob('project-merge', B)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # Both -merge jobs have run, but no others.
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        self.assertEqual(self.history[0].result, 'SUCCESS')
        self.assertEqual(self.history[0].name, 'project-merge')
        self.assertEqual(self.history[1].result, 'FAILURE')
        self.assertEqual(self.history[1].name, 'project-merge')
        self.assertEqual(len(self.history), 2)

        # Add the "project-test3" job.
        self.commitConfigUpdate('common-config',
                                'layouts/live-reconfiguration-add-job.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(self.history[0].result, 'SUCCESS')
        self.assertEqual(self.history[0].name, 'project-merge')
        self.assertEqual(self.history[1].result, 'FAILURE')
        self.assertEqual(self.history[1].name, 'project-merge')
        self.assertEqual(self.history[2].result, 'SUCCESS')
        self.assertEqual(self.history[3].result, 'SUCCESS')
        self.assertEqual(self.history[4].result, 'SUCCESS')
        self.assertEqual(len(self.history), 5)

    def test_live_reconfiguration_failed_job(self):
        # Test that a change with a removed failing job does not
        # disrupt reconfiguration.  If a change has a failed job and
        # that job is removed during a reconfiguration, we observed a
        # bug where the code to re-set build statuses would run on
        # that build and raise an exception because the job no longer
        # existed.
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')

        # This change will fail and later be removed by the reconfiguration.
        self.executor_server.failJob('project-test1', A)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('project-test1')
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 0)

        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'FAILURE')
        self.assertEqual(len(self.history), 2)

        # Remove the test1 job.
        self.commitConfigUpdate('common-config',
                                'layouts/live-reconfiguration-failed-job.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-testfile').result,
                         'SUCCESS')
        self.assertEqual(len(self.history), 4)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertIn('Build succeeded', A.messages[0])
        # Ensure the removed job was not included in the report.
        self.assertNotIn('project-test1', A.messages[0])

    def test_live_reconfiguration_shared_queue(self):
        # Test that a change with a failing job which was removed from
        # this project but otherwise still exists in the system does
        # not disrupt reconfiguration.

        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')

        self.executor_server.failJob('project1-project2-integration', A)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('project1-project2-integration')
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 0)

        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project1-project2-integration').result, 'FAILURE')
        self.assertEqual(len(self.history), 2)

        # Remove the integration job.
        self.commitConfigUpdate(
            'common-config',
            'layouts/live-reconfiguration-shared-queue.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project1-project2-integration').result, 'FAILURE')
        self.assertEqual(len(self.history), 4)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertIn('Build succeeded', A.messages[0])
        # Ensure the removed job was not included in the report.
        self.assertNotIn('project1-project2-integration', A.messages[0])

    def test_double_live_reconfiguration_shared_queue(self):
        # This was a real-world regression.  A change is added to
        # gate; a reconfigure happens, a second change which depends
        # on the first is added, and a second reconfiguration happens.
        # Ensure that both changes merge.

        # A failure may indicate incorrect caching or cleaning up of
        # references during a reconfiguration.
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.setDependsOn(A, 1)
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        # Add the parent change.
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # Reconfigure (with only one change in the pipeline).
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        # Add the child change.
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # Reconfigure (with both in the pipeline).
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 8)

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_live_reconfiguration_del_project(self):
        # Test project deletion from layout
        # while changes are enqueued

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 5)

        # This layout defines only org/project, not org/project1
        self.commitConfigUpdate(
            'common-config',
            'layouts/live-reconfiguration-del-project.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        # Builds for C aborted, builds for A succeed,
        # and have change B applied ahead
        job_c = self.getJobFromHistory('project-test1')
        self.assertEqual(job_c.changes, '3,1')
        self.assertEqual(job_c.result, 'ABORTED')

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(
            self.getJobFromHistory('project-test1', 'org/project').changes,
            '2,1 1,1')

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)
        self.assertEqual(C.reported, 0)

        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)
        self.assertIn('Build succeeded', A.messages[0])

    @simple_layout("layouts/reconfigure-failed-head.yaml")
    def test_live_reconfiguration_failed_change_at_head(self):
        # Test that if we reconfigure with a failed change at head,
        # that the change behind it isn't reparented onto it.

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)

        self.executor_server.failJob('job1', A)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='job1', changes='1,1'),
            dict(name='job2', changes='1,1'),
            dict(name='job1', changes='1,1 2,1'),
            dict(name='job2', changes='1,1 2,1'),
        ])

        self.release(self.builds[0])
        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='job2', changes='1,1'),
            dict(name='job1', changes='2,1'),
            dict(name='job2', changes='2,1'),
        ])

        # Unordered history comparison because the aborts can finish
        # in any order.
        self.assertHistory([
            dict(name='job1', result='FAILURE', changes='1,1'),
            dict(name='job1', result='ABORTED', changes='1,1 2,1'),
            dict(name='job2', result='ABORTED', changes='1,1 2,1'),
        ], ordered=False)

        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertBuilds([])

        self.assertHistory([
            dict(name='job1', result='FAILURE', changes='1,1'),
            dict(name='job1', result='ABORTED', changes='1,1 2,1'),
            dict(name='job2', result='ABORTED', changes='1,1 2,1'),
            dict(name='job2', result='SUCCESS', changes='1,1'),
            dict(name='job1', result='SUCCESS', changes='2,1'),
            dict(name='job2', result='SUCCESS', changes='2,1'),
        ], ordered=False)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

    def test_delayed_repo_init(self):
        self.init_repo("org/new-project")
        files = {'README': ''}
        self.addCommitToRepo("org/new-project", 'Initial commit',
                             files=files, tag='init')
        self.newTenantConfig('tenants/delayed-repo-init.yaml')
        self.commitConfigUpdate(
            'common-config',
            'layouts/delayed-repo-init.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange('org/new-project', 'master', 'A')

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

    @simple_layout('layouts/repo-deleted.yaml')
    def test_repo_deleted(self):
        self.init_repo("org/delete-project")
        A = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'A')

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

        # Delete org/new-project zuul repo. Should be recloned.
        p = 'org/delete-project'
        if os.path.exists(os.path.join(self.merger_src_root, p)):
            shutil.rmtree(os.path.join(self.merger_src_root, p))
        if os.path.exists(os.path.join(self.executor_src_root, p)):
            shutil.rmtree(os.path.join(self.executor_src_root, p))

        B = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'B')

        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    @simple_layout('layouts/untrusted-secrets.yaml')
    def test_untrusted_secrets(self):
        "Test untrusted secrets"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([])
        self.assertEqual(A.patchsets[0]['approvals'][0]['value'], "-1")
        self.assertIn('does not allow post-review job',
                      A.messages[0])

    @simple_layout('layouts/tags.yaml')
    def test_tags(self):
        "Test job tags"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)

        results = {self.getJobFromHistory('merge',
                   project='org/project1').uuid: ['extratag', 'merge'],
                   self.getJobFromHistory('merge',
                   project='org/project2').uuid: ['merge']}

        for build in self.history:
            self.assertEqual(results.get(build.uuid, ''),
                             build.parameters['zuul'].get('jobtags'))

    def test_timer_template(self):
        "Test that a periodic job is triggered"
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.create_branch('org/project', 'stable')
        self.executor_server.hold_jobs_in_build = True
        self.commitConfigUpdate('common-config', 'layouts/timer-template.yaml')
        self.sched.reconfigure(self.config)

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)

        merge_count_project1 = 0
        for job in self.gearman_server.jobs_history:
            if job.name == b'merger:refstate':
                args = job.arguments
                if isinstance(args, bytes):
                    args = args.decode('utf-8')
                args = json.loads(args)
                if args["items"][0]["project"] == "org/project1":
                    merge_count_project1 += 1
        self.assertEquals(merge_count_project1, 0,
                          "project1 shouldn't have any refstate call")

        self.executor_server.hold_jobs_in_build = False
        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.commitConfigUpdate('common-config', 'layouts/no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-bitrot', result='SUCCESS',
                 ref='refs/heads/master'),
            dict(name='project-bitrot', result='SUCCESS',
                 ref='refs/heads/stable'),
        ], ordered=False)

    def test_timer(self):
        "Test that a periodic job is triggered"
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.create_branch('org/project', 'stable')
        self.executor_server.hold_jobs_in_build = True
        self.commitConfigUpdate('common-config', 'layouts/timer.yaml')
        self.sched.reconfigure(self.config)

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)

        merge_count_project1 = 0
        for job in self.gearman_server.jobs_history:
            if job.name == b'merger:refstate':
                args = job.arguments
                if isinstance(args, bytes):
                    args = args.decode('utf-8')
                args = json.loads(args)
                if args["items"][0]["project"] == "org/project1":
                    merge_count_project1 += 1
        self.assertEquals(merge_count_project1, 0,
                          "project1 shouldn't have any refstate call")

        self.executor_server.hold_jobs_in_build = False
        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.commitConfigUpdate('common-config', 'layouts/no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()

        # Ensure that the status json has the ref so we can render it in the
        # web ui.
        data = json.loads(self.sched.formatStatusJSON('tenant-one'))
        pipeline = [x for x in data['pipelines'] if x['name'] == 'periodic'][0]
        first = pipeline['change_queues'][0]['heads'][0][0]
        second = pipeline['change_queues'][1]['heads'][0][0]
        self.assertIn(first['ref'], ['refs/heads/master', 'refs/heads/stable'])
        self.assertIn(second['ref'],
                      ['refs/heads/master', 'refs/heads/stable'])

        self.executor_server.release()
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-bitrot', result='SUCCESS',
                 ref='refs/heads/master'),
            dict(name='project-bitrot', result='SUCCESS',
                 ref='refs/heads/stable'),
        ], ordered=False)

    def test_idle(self):
        "Test that frequent periodic jobs work"
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.executor_server.hold_jobs_in_build = True

        for x in range(1, 3):
            # Test that timer triggers periodic jobs even across
            # layout config reloads.
            # Start timer trigger
            self.commitConfigUpdate('common-config',
                                    'layouts/idle.yaml')
            self.sched.reconfigure(self.config)
            self.waitUntilSettled()

            # The pipeline triggers every second, so we should have seen
            # several by now.
            time.sleep(5)

            # Stop queuing timer triggered jobs so that the assertions
            # below don't race against more jobs being queued.
            self.commitConfigUpdate('common-config',
                                    'layouts/no-timer.yaml')
            self.sched.reconfigure(self.config)
            self.waitUntilSettled()
            # If APScheduler is in mid-event when we remove the job,
            # we can end up with one more event firing, so give it an
            # extra second to settle.
            time.sleep(1)
            self.waitUntilSettled()
            self.assertEqual(len(self.builds), 1,
                             'Timer builds iteration #%d' % x)
            self.executor_server.release('.*')
            self.waitUntilSettled()
            self.assertEqual(len(self.builds), 0)
            self.assertEqual(len(self.history), x)

    @simple_layout('layouts/smtp.yaml')
    def test_check_smtp_pool(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.smtp_messages), 2)

        # A.messages only holds what FakeGerrit places in it. Thus we
        # work on the knowledge of what the first message should be as
        # it is only configured to go to SMTP.

        self.assertEqual('zuul@example.com',
                         self.smtp_messages[0]['from_email'])
        self.assertEqual(['you@example.com'],
                         self.smtp_messages[0]['to_email'])
        self.assertEqual('Starting check jobs.',
                         self.smtp_messages[0]['body'])

        self.assertEqual('zuul_from@example.com',
                         self.smtp_messages[1]['from_email'])
        self.assertEqual(['alternative_me@example.com'],
                         self.smtp_messages[1]['to_email'])
        self.assertEqual(A.messages[0],
                         self.smtp_messages[1]['body'])

    @simple_layout('layouts/smtp.yaml')
    @mock.patch('zuul.driver.gerrit.gerritreporter.GerritReporter.report')
    def test_failed_reporter(self, report_mock):
        '''Test that one failed reporter doesn't break other reporters'''
        # Warning hacks. We sort the reports here so that the test is
        # deterministic. Gerrit reporting will fail, but smtp reporting
        # should succeed.
        report_mock.side_effect = Exception('Gerrit failed to report')

        tenant = self.sched.abide.tenants.get('tenant-one')
        check = tenant.layout.pipelines['check']

        check.success_actions = sorted(check.success_actions,
                                       key=lambda x: x.name)
        self.assertEqual(check.success_actions[0].name, 'gerrit')
        self.assertEqual(check.success_actions[1].name, 'smtp')

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # We know that if gerrit ran first and failed and smtp ran second
        # and sends mail then we handle failures in reporters gracefully.
        self.assertEqual(len(self.smtp_messages), 2)

        # A.messages only holds what FakeGerrit places in it. Thus we
        # work on the knowledge of what the first message should be as
        # it is only configured to go to SMTP.

        self.assertEqual('zuul@example.com',
                         self.smtp_messages[0]['from_email'])
        self.assertEqual(['you@example.com'],
                         self.smtp_messages[0]['to_email'])
        self.assertEqual('Starting check jobs.',
                         self.smtp_messages[0]['body'])

        self.assertEqual('zuul_from@example.com',
                         self.smtp_messages[1]['from_email'])
        self.assertEqual(['alternative_me@example.com'],
                         self.smtp_messages[1]['to_email'])
        # This double checks that Gerrit side failed
        self.assertEqual(A.messages, [])

    def test_timer_smtp(self):
        "Test that a periodic job is triggered"
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.executor_server.hold_jobs_in_build = True
        self.commitConfigUpdate('common-config', 'layouts/timer-smtp.yaml')
        self.sched.reconfigure(self.config)

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        self.executor_server.release('.*')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)

        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-old').result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-older').result, 'SUCCESS')

        self.assertEqual(len(self.smtp_messages), 1)

        # A.messages only holds what FakeGerrit places in it. Thus we
        # work on the knowledge of what the first message should be as
        # it is only configured to go to SMTP.

        self.assertEqual('zuul_from@example.com',
                         self.smtp_messages[0]['from_email'])
        self.assertEqual(['alternative_me@example.com'],
                         self.smtp_messages[0]['to_email'])
        self.assertIn('Subject: Periodic check for org/project succeeded',
                      self.smtp_messages[0]['headers'])

        # Stop queuing timer triggered jobs and let any that may have
        # queued through so that end of test assertions pass.
        self.commitConfigUpdate('common-config', 'layouts/no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()
        self.executor_server.release('.*')
        self.waitUntilSettled()

    @skip("Disabled for early v3 development")
    def test_timer_sshkey(self):
        "Test that a periodic job can setup SSH key authentication"
        self.worker.hold_jobs_in_build = True
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)

        ssh_wrapper = os.path.join(self.git_root, ".ssh_wrapper_gerrit")
        self.assertTrue(os.path.isfile(ssh_wrapper))
        with open(ssh_wrapper) as f:
            ssh_wrapper_content = f.read()
        self.assertIn("fake_id_rsa", ssh_wrapper_content)
        # In the unit tests Merger runs in the same process,
        # so we see its' environment variables
        self.assertEqual(os.environ['GIT_SSH'], ssh_wrapper)

        self.worker.release('.*')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)

        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-old').result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-older').result, 'SUCCESS')

        # Stop queuing timer triggered jobs and let any that may have
        # queued through so that end of test assertions pass.
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()
        self.worker.release('.*')
        self.waitUntilSettled()

    def test_client_enqueue_change(self):
        "Test that the RPC client can enqueue a change"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        A.addApproval('Approved', 1)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.enqueue(tenant='tenant-one',
                           pipeline='gate',
                           project='org/project',
                           trigger='gerrit',
                           change='1,1')
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(r, True)

    @simple_layout('layouts/three-projects.yaml')
    def test_client_enqueue_change_wrong_project(self):
        "Test that an enqueue fails if a change doesn't belong to the project"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addApproval('Code-Review', 2)
        A.addApproval('Approved', 1)

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        B.addApproval('Code-Review', 2)
        B.addApproval('Approved', 1)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        with testtools.ExpectedException(
            zuul.rpcclient.RPCFailure,
            'Change 2,1 does not belong to project "org/project1"'):
            r = client.enqueue(tenant='tenant-one',
                               pipeline='gate',
                               project='org/project1',
                               trigger='gerrit',
                               change='2,1')
            self.assertEqual(r, False)
        self.waitUntilSettled()

    def test_client_enqueue_ref(self):
        "Test that the RPC client can enqueue a ref"
        p = "review.example.com/org/project"
        upstream = self.getUpstreamRepos([p])
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.setMerged()
        A_commit = str(upstream[p].commit('master'))
        self.log.debug("A commit: %s" % A_commit)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.enqueue_ref(
            tenant='tenant-one',
            pipeline='post',
            project='org/project',
            trigger='gerrit',
            ref='master',
            oldrev='90f173846e3af9154517b88543ffbd1691f31366',
            newrev=A_commit)
        self.waitUntilSettled()
        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 1)
        self.assertIn('project-post', job_names)
        self.assertEqual(r, True)

    def test_client_dequeue_dependent_change(self):
        "Test that the RPC client can dequeue a change"
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        # Promote to 'gate' pipeline
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        client.dequeue(
            tenant='tenant-one',
            pipeline='gate',
            project='org/project',
            change='1,1',
            ref=None)

        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        gate_pipeline = tenant.layout.pipelines['gate']
        self.assertEqual(gate_pipeline.getAllItems(), [])
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_client_dequeue_independent_change(self):
        "Test that the RPC client can dequeue a change"

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        client.dequeue(
            tenant='tenant-one',
            pipeline='check',
            project='org/project',
            change='1,1',
            ref=None)
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']
        self.assertEqual(len(check_pipeline.getAllItems()), 2)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/three-projects.yaml')
    def test_client_dequeue_wrong_project(self):
        "Test that dequeue fails if change and project do not match"

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        with testtools.ExpectedException(
            zuul.rpcclient.RPCFailure,
            'Change 4,1 does not belong to project "org/project1"'):
            r = client.dequeue(
                tenant='tenant-one',
                pipeline='check',
                project='org/project1',
                change='4,1',
                ref=None)
            self.waitUntilSettled()
            self.assertEqual(r, False)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_client_dequeue_change_by_ref(self):
        "Test that the RPC client can dequeue a change by ref"
        # Test this on the periodic pipeline, where it makes most sense to
        # use ref
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        self.create_branch('org/project', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'stable'))
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = True
        self.commitConfigUpdate('common-config', 'layouts/timer.yaml')
        self.sched.reconfigure(self.config)

        # We expect that one build for each branch (master and stable) appears.
        for _ in iterate_timeout(30, 'Wait for two builds that are hold'):
            if len(self.builds) == 2:
                break
        self.waitUntilSettled()

        client.dequeue(
            tenant='tenant-one',
            pipeline='periodic',
            project='org/project',
            change=None,
            ref='refs/heads/stable')
        self.waitUntilSettled()

        self.commitConfigUpdate('common-config',
                                'layouts/no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

    def test_client_enqueue_negative(self):
        "Test that the RPC client returns errors"
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid tenant"):
            r = client.enqueue(tenant='tenant-foo',
                               pipeline='gate',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid project"):
            r = client.enqueue(tenant='tenant-one',
                               pipeline='gate',
                               project='project-does-not-exist',
                               trigger='gerrit',
                               change='1,1')
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid pipeline"):
            r = client.enqueue(tenant='tenant-one',
                               pipeline='pipeline-does-not-exist',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid trigger"):
            r = client.enqueue(tenant='tenant-one',
                               pipeline='gate',
                               project='org/project',
                               trigger='trigger-does-not-exist',
                               change='1,1')
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid change"):
            r = client.enqueue(tenant='tenant-one',
                               pipeline='gate',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            self.assertEqual(r, False)

        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)
        self.assertEqual(len(self.builds), 0)

    def test_client_enqueue_ref_negative(self):
        "Test that the RPC client returns errors"
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "New rev must be 40 character sha1"):
            r = client.enqueue_ref(
                tenant='tenant-one',
                pipeline='post',
                project='org/project',
                trigger='gerrit',
                ref='master',
                oldrev='90f173846e3af9154517b88543ffbd1691f31366',
                newrev='10054041')
            self.assertEqual(r, False)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Old rev must be 40 character sha1"):
            r = client.enqueue_ref(
                tenant='tenant-one',
                pipeline='post',
                project='org/project',
                trigger='gerrit',
                ref='master',
                oldrev='10054041',
                newrev='90f173846e3af9154517b88543ffbd1691f31366')
            self.assertEqual(r, False)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "New rev must be base16 hash"):
            r = client.enqueue_ref(
                tenant='tenant-one',
                pipeline='post',
                project='org/project',
                trigger='gerrit',
                ref='master',
                oldrev='90f173846e3af9154517b88543ffbd1691f31366',
                newrev='notbase16')
            self.assertEqual(r, False)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Old rev must be base16 hash"):
            r = client.enqueue_ref(
                tenant='tenant-one',
                pipeline='post',
                project='org/project',
                trigger='gerrit',
                ref='master',
                oldrev='notbase16',
                newrev='90f173846e3af9154517b88543ffbd1691f31366')
            self.assertEqual(r, False)

    def test_client_promote(self):
        "Test that the RPC client can promote a change"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        items = tenant.layout.pipelines['gate'].getAllItems()
        enqueue_times = {}
        for item in items:
            enqueue_times[str(item.change)] = item.enqueue_time

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.promote(tenant='tenant-one',
                           pipeline='gate',
                           change_ids=['2,1', '3,1'])

        # ensure that enqueue times are durable
        items = tenant.layout.pipelines['gate'].getAllItems()
        for item in items:
            self.assertEqual(
                enqueue_times[str(item.change)], item.enqueue_time)

        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.builds[0].hasChanges(B))
        self.assertFalse(self.builds[0].hasChanges(A))
        self.assertFalse(self.builds[0].hasChanges(C))

        self.assertTrue(self.builds[2].hasChanges(B))
        self.assertTrue(self.builds[2].hasChanges(C))
        self.assertFalse(self.builds[2].hasChanges(A))

        self.assertTrue(self.builds[4].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(C))
        self.assertTrue(self.builds[4].hasChanges(A))

        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        self.assertEqual(r, True)

    def test_client_promote_dependent(self):
        "Test that the RPC client can promote a dependent change"
        # C (depends on B) -> B -> A ; then promote C to get:
        # A -> C (depends on B) -> B
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.promote(tenant='tenant-one',
                           pipeline='gate',
                           change_ids=['3,1'])

        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.builds[0].hasChanges(B))
        self.assertFalse(self.builds[0].hasChanges(A))
        self.assertFalse(self.builds[0].hasChanges(C))

        self.assertTrue(self.builds[2].hasChanges(B))
        self.assertTrue(self.builds[2].hasChanges(C))
        self.assertFalse(self.builds[2].hasChanges(A))

        self.assertTrue(self.builds[4].hasChanges(B))
        self.assertTrue(self.builds[4].hasChanges(C))
        self.assertTrue(self.builds[4].hasChanges(A))

        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        self.assertEqual(r, True)

    def test_client_promote_negative(self):
        "Test that the RPC client returns errors for promotion"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(tenant='tenant-one',
                               pipeline='nonexistent',
                               change_ids=['2,1', '3,1'])
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(tenant='tenant-one',
                               pipeline='gate',
                               change_ids=['4,1'])
            self.assertEqual(r, False)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/rate-limit.yaml')
    def test_queue_rate_limiting(self):
        "Test that DependentPipelines are rate limited with dep across window"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)
        self.executor_server.failJob('project-test1', A)

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        # Release the merge jobs one at a time.
        self.builds[0].release()
        self.waitUntilSettled()
        self.builds[0].release()
        self.waitUntilSettled()

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.executor_server.release('project-.*')
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')

        # Gate is reset and only B's merge job is queued because
        # window shrunk to 1.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # Only B's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.executor_server.release('project-.*')
        self.waitUntilSettled()

        # B was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(B.data['status'], 'MERGED')

        # Only C is left and its merge job is queued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        # After successful merge job the test jobs for C are queued.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.executor_server.release('project-.*')
        self.waitUntilSettled()

        # C successfully merged so window is bumped to 3.
        self.assertEqual(queue.window, 3)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    @simple_layout('layouts/rate-limit.yaml')
    def test_queue_rate_limiting_dependent(self):
        "Test that DependentPipelines are rate limited with dep in window"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        B.setDependsOn(A, 1)

        self.executor_server.failJob('project-test1', A)

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        self.orderedRelease(2)

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.executor_server.release('project-.*')
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        # Gate is reset and only C's merge job is queued because
        # window shrunk to 1 and A and B were dequeued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.orderedRelease(1)

        # Only C's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        builds = self.getSortedBuilds()
        self.assertEqual(builds[0].name, 'project-test1')
        self.assertEqual(builds[1].name, 'project-test2')

        self.executor_server.release('project-.*')
        self.waitUntilSettled()

        # C was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    @simple_layout('layouts/reconfigure-window.yaml')
    def test_reconfigure_window_shrink(self):
        # Test the active window shrinking during reconfiguration
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 20)
        self.assertTrue(len(self.builds), 4)

        self.executor_server.release('job1')
        self.waitUntilSettled()
        self.commitConfigUpdate('org/common-config',
                                'layouts/reconfigure-window2.yaml')
        self.sched.reconfigure(self.config)
        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        # Even though we have configured a smaller window, the value
        # on the existing shared queue should be used.
        self.assertEqual(queue.window, 20)
        self.assertTrue(len(self.builds), 4)

        self.sched.reconfigure(self.config)
        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 20)
        self.assertTrue(len(self.builds), 4)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        self.assertHistory([
            dict(name='job1', result='SUCCESS', changes='1,1'),
            dict(name='job1', result='SUCCESS', changes='1,1 2,1'),
            dict(name='job2', result='SUCCESS', changes='1,1'),
            dict(name='job2', result='SUCCESS', changes='1,1 2,1'),
        ], ordered=False)

    @simple_layout('layouts/reconfigure-window-fixed.yaml')
    def test_reconfigure_window_fixed(self):
        # Test the active window shrinking during reconfiguration
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 2)
        self.assertEqual(len(self.builds), 4)

        self.waitUntilSettled()
        self.commitConfigUpdate('org/common-config',
                                'layouts/reconfigure-window-fixed2.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        # Because we have configured a static window, it should
        # be allowed to shrink on reconfiguration.
        self.assertEqual(queue.window, 1)
        # B is outside the window, but still marked active until the
        # next pass through the queue processor, so its builds haven't
        # been canceled.
        self.assertEqual(len(self.builds), 4)

        self.sched.reconfigure(self.config)
        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 1)
        self.waitUntilSettled()
        # B's builds have been canceled now
        self.assertEqual(len(self.builds), 2)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        # B's builds will be restarted and will show up in our history
        # twice.
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='job1', result='SUCCESS', changes='1,1'),
            dict(name='job1', result='ABORTED', changes='1,1 2,1'),
            dict(name='job2', result='SUCCESS', changes='1,1'),
            dict(name='job2', result='ABORTED', changes='1,1 2,1'),
            dict(name='job1', result='SUCCESS', changes='1,1 2,1'),
            dict(name='job2', result='SUCCESS', changes='1,1 2,1'),
        ], ordered=False)

    @simple_layout('layouts/reconfigure-window-fixed.yaml')
    def test_reconfigure_window_fixed_requests(self):
        # Test the active window shrinking during reconfiguration with
        # outstanding node requests
        self.executor_server.hold_jobs_in_build = True

        # Start the jobs for A
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.log.debug("A complete")

        # Hold node requests for B
        self.fake_nodepool.pause()
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.log.debug("B complete")

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 2)
        self.assertEqual(len(self.builds), 2)

        self.waitUntilSettled()
        self.commitConfigUpdate('org/common-config',
                                'layouts/reconfigure-window-fixed2.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        self.log.debug("Reconfiguration complete")

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        # Because we have configured a static window, it should
        # be allowed to shrink on reconfiguration.
        self.assertEqual(queue.window, 1)
        self.assertEqual(len(self.builds), 2)

        # After the previous reconfig, the queue processor will have
        # run and marked B inactive; run another reconfiguration so
        # that we're testing what happens when we reconfigure after
        # the active window having shrunk.
        self.sched.reconfigure(self.config)

        # Unpause the node requests now
        self.fake_nodepool.unpause()
        self.waitUntilSettled()
        self.log.debug("Nodepool unpause complete")

        # Allow A to merge and B to enter the active window and complete
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.log.debug("Executor unpause complete")

        tenant = self.sched.abide.tenants.get('tenant-one')
        queue = tenant.layout.pipelines['gate'].queues[0]
        self.assertEqual(queue.window, 1)

        self.waitUntilSettled()
        self.assertHistory([
            dict(name='job1', result='SUCCESS', changes='1,1'),
            dict(name='job2', result='SUCCESS', changes='1,1'),
            dict(name='job1', result='SUCCESS', changes='1,1 2,1'),
            dict(name='job2', result='SUCCESS', changes='1,1 2,1'),
        ], ordered=False)

    @simple_layout('layouts/reconfigure-remove-add.yaml')
    def test_reconfigure_remove_add(self):
        # Test removing, then adding a job while in queue
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertTrue(len(self.builds), 2)
        self.executor_server.release('job2')
        self.assertTrue(len(self.builds), 1)

        # Remove job2
        self.commitConfigUpdate('org/common-config',
                                'layouts/reconfigure-remove-add2.yaml')
        self.sched.reconfigure(self.config)
        self.assertTrue(len(self.builds), 1)

        # Add job2 back
        self.commitConfigUpdate('org/common-config',
                                'layouts/reconfigure-remove-add.yaml')
        self.sched.reconfigure(self.config)
        self.assertTrue(len(self.builds), 2)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        # This will run new builds for B
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='job2', result='SUCCESS', changes='1,1'),
            dict(name='job1', result='SUCCESS', changes='1,1'),
            dict(name='job2', result='SUCCESS', changes='1,1'),
        ], ordered=False)

    def test_worker_update_metadata(self):
        "Test if a worker can send back metadata about itself"
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.executor_client.builds), 1)

        self.log.debug('Current builds:')
        self.log.debug(self.executor_client.builds)

        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = list(self.executor_client.builds.values())[0]
            if build.worker.name == self.executor_server.hostname:
                break
            else:
                time.sleep(0)

        self.log.debug(build)
        self.assertEqual(self.executor_server.hostname, build.worker.name)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/footer-message.yaml')
    def test_footer_message(self):
        "Test a pipeline's footer message is correctly added to the report."
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.executor_server.failJob('project-test1', A)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(2, len(self.smtp_messages))

        failure_msg = """\
Build failed.  For information on how to proceed, see \
http://wiki.example.org/Test_Failures"""

        footer_msg = """\
For CI problems and help debugging, contact ci@example.org"""

        self.assertTrue(self.smtp_messages[0]['body'].startswith(failure_msg))
        self.assertTrue(self.smtp_messages[0]['body'].endswith(footer_msg))
        self.assertFalse(self.smtp_messages[1]['body'].startswith(failure_msg))
        self.assertTrue(self.smtp_messages[1]['body'].endswith(footer_msg))

    @simple_layout('layouts/unmanaged-project.yaml')
    def test_unmanaged_project_start_message(self):
        "Test start reporting is not done for unmanaged projects."
        self.init_repo("org/project", tag='init')
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(0, len(A.messages))

    @simple_layout('layouts/merge-failure.yaml')
    def test_merge_failure_reporters(self):
        """Check that the config is set up correctly"""

        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(
            "Merge Failed.\n\nThis change or one of its cross-repo "
            "dependencies was unable to be automatically merged with the "
            "current state of its repository. Please rebase the change and "
            "upload a new patchset.",
            tenant.layout.pipelines['check'].merge_failure_message)
        self.assertEqual(
            "The merge failed! For more information...",
            tenant.layout.pipelines['gate'].merge_failure_message)

        self.assertEqual(
            len(tenant.layout.pipelines['check'].merge_failure_actions), 1)
        self.assertEqual(
            len(tenant.layout.pipelines['gate'].merge_failure_actions), 2)

        self.assertTrue(isinstance(
            tenant.layout.pipelines['check'].merge_failure_actions[0],
            gerritreporter.GerritReporter))

        self.assertTrue(
            (
                isinstance(tenant.layout.pipelines['gate'].
                           merge_failure_actions[0],
                           zuul.driver.smtp.smtpreporter.SMTPReporter) and
                isinstance(tenant.layout.pipelines['gate'].
                           merge_failure_actions[1],
                           gerritreporter.GerritReporter)
            ) or (
                isinstance(tenant.layout.pipelines['gate'].
                           merge_failure_actions[0],
                           gerritreporter.GerritReporter) and
                isinstance(tenant.layout.pipelines['gate'].
                           merge_failure_actions[1],
                           zuul.driver.smtp.smtpreporter.SMTPReporter)
            )
        )

    @skip("Disabled for early v3 development")
    def test_merge_failure_reports(self):
        """Check that when a change fails to merge the correct message is sent
        to the correct reporter"""
        self.updateConfigLayout(
            'tests/fixtures/layout-merge-failure.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # Check a test failure isn't reported to SMTP
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.executor_server.failJob('project-test1', A)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(3, len(self.history))  # 3 jobs
        self.assertEqual(0, len(self.smtp_messages))

        # Check a merge failure is reported to SMTP
        # B should be merged, but C will conflict with B
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset(['conflict'])
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.addPatchset(['conflict'])
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(6, len(self.history))  # A and B jobs
        self.assertEqual(1, len(self.smtp_messages))
        self.assertEqual('The merge failed! For more information...',
                         self.smtp_messages[0]['body'])

    @skip("Disabled for early v3 development")
    def test_default_merge_failure_reports(self):
        """Check that the default merge failure reports are correct."""

        # A should report success, B should report merge failure.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset(['conflict'])
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset(['conflict'])
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(3, len(self.history))  # A jobs
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertIn('Build succeeded', A.messages[1])
        self.assertIn('Merge Failed', B.messages[1])
        self.assertIn('automatically merged', B.messages[1])
        self.assertNotIn('logs.example.com', B.messages[1])
        self.assertNotIn('SKIPPED', B.messages[1])

    def test_client_get_running_jobs(self):
        "Test that the RPC client can get a list of running jobs"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)

        # Wait for gearman server to send the initial workData back to zuul
        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = list(self.executor_client.builds.values())[0]
            if build.worker.name == self.executor_server.hostname:
                break
            else:
                time.sleep(0)

        running_items = client.get_running_jobs()

        self.assertEqual(1, len(running_items))
        running_item = running_items[0]
        self.assertEqual([], running_item['failing_reasons'])
        self.assertEqual([], running_item['items_behind'])
        self.assertEqual('https://review.example.com/1', running_item['url'])
        self.assertIsNone(running_item['item_ahead'])
        self.assertEqual('org/project', running_item['project'])
        self.assertIsNone(running_item['remaining_time'])
        self.assertEqual(True, running_item['active'])
        self.assertEqual('1,1', running_item['id'])

        self.assertEqual(3, len(running_item['jobs']))
        for job in running_item['jobs']:
            if job['name'] == 'project-merge':
                self.assertEqual('project-merge', job['name'])
                self.assertEqual('gate', job['pipeline'])
                self.assertEqual(False, job['retry'])
                self.assertEqual(
                    'stream/{uuid}?logfile=console.log'
                    .format(uuid=job['uuid']), job['url'])
                self.assertEqual(
                    'finger://{hostname}/{uuid}'.format(
                        hostname=self.executor_server.hostname,
                        uuid=job['uuid']),
                    job['finger_url'])
                self.assertEqual(2, len(job['worker']))
                self.assertEqual(False, job['canceled'])
                self.assertEqual(True, job['voting'])
                self.assertIsNone(job['result'])
                self.assertEqual('gate', job['pipeline'])
                break

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        running_items = client.get_running_jobs()
        self.assertEqual(0, len(running_items))

    @simple_layout('layouts/nonvoting-pipeline.yaml')
    def test_nonvoting_pipeline(self):
        "Test that a nonvoting pipeline (experimental) can still report"

        A = self.fake_gerrit.addFakeChange('org/experimental-project',
                                           'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('experimental-project-test').result,
            'SUCCESS')
        self.assertEqual(A.reported, 1)

    @simple_layout('layouts/disable_at.yaml')
    def test_disable_at(self):
        "Test a pipeline will only report to the disabled trigger when failing"

        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(3, tenant.layout.pipelines['check'].disable_at)
        self.assertEqual(
            0, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertFalse(tenant.layout.pipelines['check']._disabled)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        F = self.fake_gerrit.addFakeChange('org/project', 'master', 'F')
        G = self.fake_gerrit.addFakeChange('org/project', 'master', 'G')
        H = self.fake_gerrit.addFakeChange('org/project', 'master', 'H')
        I = self.fake_gerrit.addFakeChange('org/project', 'master', 'I')
        J = self.fake_gerrit.addFakeChange('org/project', 'master', 'J')
        K = self.fake_gerrit.addFakeChange('org/project', 'master', 'K')

        self.executor_server.failJob('project-test1', A)
        self.executor_server.failJob('project-test1', B)
        # Let C pass, resetting the counter
        self.executor_server.failJob('project-test1', D)
        self.executor_server.failJob('project-test1', E)
        self.executor_server.failJob('project-test1', F)
        self.executor_server.failJob('project-test1', G)
        self.executor_server.failJob('project-test1', H)
        # I also passes but should only report to the disabled reporters
        self.executor_server.failJob('project-test1', J)
        self.executor_server.failJob('project-test1', K)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(
            2, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertFalse(tenant.layout.pipelines['check']._disabled)

        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(
            0, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertFalse(tenant.layout.pipelines['check']._disabled)

        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(E.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(F.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # We should be disabled now
        self.assertEqual(
            3, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertTrue(tenant.layout.pipelines['check']._disabled)

        # We need to wait between each of these patches to make sure the
        # smtp messages come back in an expected order
        self.fake_gerrit.addEvent(G.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(H.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(I.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # The first 6 (ABCDEF) jobs should have reported back to gerrt thus
        # leaving a message on each change
        self.assertEqual(1, len(A.messages))
        self.assertIn('Build failed.', A.messages[0])
        self.assertEqual(1, len(B.messages))
        self.assertIn('Build failed.', B.messages[0])
        self.assertEqual(1, len(C.messages))
        self.assertIn('Build succeeded.', C.messages[0])
        self.assertEqual(1, len(D.messages))
        self.assertIn('Build failed.', D.messages[0])
        self.assertEqual(1, len(E.messages))
        self.assertIn('Build failed.', E.messages[0])
        self.assertEqual(1, len(F.messages))
        self.assertIn('Build failed.', F.messages[0])

        # The last 3 (GHI) would have only reported via smtp.
        self.assertEqual(3, len(self.smtp_messages))
        self.assertEqual(0, len(G.messages))
        self.assertIn('Build failed.', self.smtp_messages[0]['body'])
        self.assertIn(
            'project-test1 finger://', self.smtp_messages[0]['body'])
        self.assertEqual(0, len(H.messages))
        self.assertIn('Build failed.', self.smtp_messages[1]['body'])
        self.assertIn(
            'project-test1 finger://', self.smtp_messages[1]['body'])
        self.assertEqual(0, len(I.messages))
        self.assertIn('Build succeeded.', self.smtp_messages[2]['body'])
        self.assertIn(
            'project-test1 finger://', self.smtp_messages[2]['body'])

        # Now reload the configuration (simulate a HUP) to check the pipeline
        # comes out of disabled
        self.sched.reconfigure(self.config)

        tenant = self.sched.abide.tenants.get('tenant-one')

        self.assertEqual(3, tenant.layout.pipelines['check'].disable_at)
        self.assertEqual(
            0, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertFalse(tenant.layout.pipelines['check']._disabled)

        self.fake_gerrit.addEvent(J.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(K.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(
            2, tenant.layout.pipelines['check']._consecutive_failures)
        self.assertFalse(tenant.layout.pipelines['check']._disabled)

        # J and K went back to gerrit
        self.assertEqual(1, len(J.messages))
        self.assertIn('Build failed.', J.messages[0])
        self.assertEqual(1, len(K.messages))
        self.assertIn('Build failed.', K.messages[0])
        # No more messages reported via smtp
        self.assertEqual(3, len(self.smtp_messages))

    @simple_layout('layouts/one-job-project.yaml')
    def test_one_job_project(self):
        "Test that queueing works with one job"
        A = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_job_aborted(self):
        "Test that if a execute server aborts a job, it is run again"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)

        # first abort
        self.builds[0].aborted = True
        self.executor_server.release('.*-test*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)

        # second abort
        self.builds[0].aborted = True
        self.executor_server.release('.*-test*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)

        # third abort
        self.builds[0].aborted = True
        self.executor_server.release('.*-test*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)

        # fourth abort
        self.builds[0].aborted = True
        self.executor_server.release('.*-test*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 7)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 4)
        self.assertEqual(self.countJobResults(self.history, 'SUCCESS'), 3)

    def test_rerun_on_abort(self):
        "Test that if a execute server fails to run a job, it is run again"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        self.builds[0].requeue = True
        self.executor_server.release('.*-test*')
        self.waitUntilSettled()

        for x in range(3):
            self.assertEqual(len(self.builds), 1,
                             'len of builds at x=%d is wrong' % x)
            self.builds[0].requeue = True
            self.executor_server.release('.*-test1')
            self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 6)
        self.assertEqual(self.countJobResults(self.history, 'SUCCESS'), 2)
        self.assertEqual(A.reported, 1)
        self.assertIn('RETRY_LIMIT', A.messages[0])

    def test_zookeeper_disconnect(self):
        "Test that jobs are executed after a zookeeper disconnect"

        self.fake_nodepool.pause()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.zk.client.stop()
        self.zk.client.start()
        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_zookeeper_disconnect2(self):
        "Test that jobs are executed after a zookeeper disconnect"

        # This tests receiving a ZK disconnect between the arrival of
        # a fulfilled request and when we accept its nodes.
        self.fake_nodepool.pause()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        # We're waiting on the nodepool request to complete.  Stop the
        # scheduler from processing further events, then fulfill the
        # nodepool request.
        self.sched.run_handler_lock.acquire()

        # Fulfill the nodepool request.
        self.fake_nodepool.unpause()
        requests = list(self.sched.nodepool.requests.values())
        self.assertEqual(1, len(requests))
        request = requests[0]
        for x in iterate_timeout(30, 'fulfill request'):
            if request.fulfilled:
                break
        id1 = request.id

        # The request is fulfilled, but the scheduler hasn't processed
        # it yet.  Reconnect ZK.
        self.zk.client.stop()
        self.zk.client.start()

        # Allow the scheduler to continue and process the (now
        # out-of-date) notification that nodes are ready.
        self.sched.run_handler_lock.release()

        # It should resubmit the request, once it's fulfilled, we can
        # wait for it to run jobs and settle.
        for x in iterate_timeout(30, 'fulfill request'):
            if request.fulfilled:
                break
        self.waitUntilSettled()

        id2 = request.id
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        # Make sure it was resubmitted (the id's should be different).
        self.assertNotEqual(id1, id2)

    def test_nodepool_failure(self):
        "Test that jobs are reported after a nodepool failure"

        self.fake_nodepool.pause()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        req = self.fake_nodepool.getNodeRequests()[0]
        self.fake_nodepool.addFailRequest(req)

        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertIn('project-merge : NODE_FAILURE', A.messages[1])
        self.assertIn('project-test1 : SKIPPED', A.messages[1])
        self.assertIn('project-test2 : SKIPPED', A.messages[1])

    def test_nodepool_pipeline_priority(self):
        "Test that nodes are requested at the correct pipeline priority"

        self.fake_nodepool.pause()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getRefUpdatedEvent())
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        reqs = self.fake_nodepool.getNodeRequests()

        # The requests come back sorted by priority. Since we have
        # three requests for the three changes each with a different
        # priority.  Also they get a serial number based on order they
        # were received so the number on the endof the oid should map
        # to order submitted.

        # * gate first - high priority - change C
        self.assertEqual(reqs[0]['_oid'], '100-0000000002')
        self.assertEqual(reqs[0]['node_types'], ['label1'])
        # * check second - normal priority - change B
        self.assertEqual(reqs[1]['_oid'], '200-0000000001')
        self.assertEqual(reqs[1]['node_types'], ['label1'])
        # * post third - low priority - change A
        # additionally, the post job defined uses an ubuntu-xenial node,
        # so we include that check just as an extra verification
        self.assertEqual(reqs[2]['_oid'], '300-0000000000')
        self.assertEqual(reqs[2]['node_types'], ['ubuntu-xenial'])

        self.fake_nodepool.unpause()
        self.waitUntilSettled()

    @simple_layout('layouts/two-projects-integrated.yaml')
    def test_nodepool_relative_priority_check(self):
        "Test that nodes are requested at the relative priority"

        self.fake_nodepool.pause()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        reqs = self.fake_nodepool.getNodeRequests()

        # The requests come back sorted by priority.

        # Change A, first change for project, high relative priority.
        self.assertEqual(reqs[0]['_oid'], '200-0000000000')
        self.assertEqual(reqs[0]['relative_priority'], 0)

        # Change C, first change for project1, high relative priority.
        self.assertEqual(reqs[1]['_oid'], '200-0000000002')
        self.assertEqual(reqs[1]['relative_priority'], 0)

        # Change B, second change for project, lower relative priority.
        self.assertEqual(reqs[2]['_oid'], '200-0000000001')
        self.assertEqual(reqs[2]['relative_priority'], 1)

        # Change D, first change for project2 shared with project1,
        # lower relative priority than project1.
        self.assertEqual(reqs[3]['_oid'], '200-0000000003')
        self.assertEqual(reqs[3]['relative_priority'], 1)

        # Fulfill only the first request
        self.fake_nodepool.fulfillRequest(reqs[0])
        for x in iterate_timeout(30, 'fulfill request'):
            if len(self.sched.nodepool.requests) < 4:
                break
        self.waitUntilSettled()

        reqs = self.fake_nodepool.getNodeRequests()

        # Change B, now first change for project, equal priority.
        self.assertEqual(reqs[0]['_oid'], '200-0000000001')
        self.assertEqual(reqs[0]['relative_priority'], 0)

        # Change C, now first change for project1, equal priority.
        self.assertEqual(reqs[1]['_oid'], '200-0000000002')
        self.assertEqual(reqs[1]['relative_priority'], 0)

        # Change D, first change for project2 shared with project1,
        # still lower relative priority than project1.
        self.assertEqual(reqs[2]['_oid'], '200-0000000003')
        self.assertEqual(reqs[2]['relative_priority'], 1)

        self.fake_nodepool.unpause()
        self.waitUntilSettled()

    @simple_layout('layouts/two-projects-integrated.yaml')
    def test_nodepool_relative_priority_gate(self):
        "Test that nodes are requested at the relative priority"

        self.fake_nodepool.pause()

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        # project does not share a queue with project1 and project2.
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        reqs = self.fake_nodepool.getNodeRequests()

        # The requests come back sorted by priority.

        # Change A, first change for shared queue, high relative
        # priority.
        self.assertEqual(reqs[0]['_oid'], '100-0000000000')
        self.assertEqual(reqs[0]['relative_priority'], 0)

        # Change C, first change for independent project, high
        # relative priority.
        self.assertEqual(reqs[1]['_oid'], '100-0000000002')
        self.assertEqual(reqs[1]['relative_priority'], 0)

        # Change B, second change for shared queue, lower relative
        # priority.
        self.assertEqual(reqs[2]['_oid'], '100-0000000001')
        self.assertEqual(reqs[2]['relative_priority'], 1)

        self.fake_nodepool.unpause()
        self.waitUntilSettled()

    def test_nodepool_job_removal(self):
        "Test that nodes are returned unused after job removal"

        self.fake_nodepool.pause()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.commitConfigUpdate('common-config', 'layouts/no-jobs.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertHistory([
            dict(name='gate-noop', result='SUCCESS', changes='1,1'),
        ])
        for node in self.fake_nodepool.getNodes():
            self.assertFalse(node['_lock'])
            self.assertEqual(node['state'], 'ready')

    @simple_layout('layouts/multiple-templates.yaml')
    def test_multiple_project_templates(self):
        # Test that applying multiple project templates to a project
        # doesn't alter them when used for a second project.
        A = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        build = self.getJobFromHistory('py27')
        self.assertEqual(build.parameters['zuul']['jobtags'], [])

    def test_pending_merge_in_reconfig(self):
        # Test that if we are waiting for an outstanding merge on
        # reconfiguration that we continue to do so.
        self.gearman_server.hold_merge_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.setMerged()
        self.fake_gerrit.addEvent(A.getRefUpdatedEvent())
        self.waitUntilSettled()
        # Reconfigure while we still have an outstanding merge job
        self.sched.reconfigureTenant(self.sched.abide.tenants['tenant-one'],
                                     None, None)
        self.waitUntilSettled()
        # Verify the merge job is still running and that the item is
        # in the pipeline
        self.assertEqual(len(self.sched.merger.jobs), 1)
        tenant = self.sched.abide.tenants.get('tenant-one')
        pipeline = tenant.layout.pipelines['post']
        self.assertEqual(len(pipeline.getAllItems()), 1)
        self.gearman_server.hold_merge_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/parent-matchers.yaml')
    def test_parent_matchers(self):
        "Test that if a job's parent does not match, the job does not run"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([])

        files = {'foo.txt': ''}
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B',
                                           files=files)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'bar.txt': ''}
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C',
                                           files=files)
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'foo.txt': '', 'bar.txt': ''}
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D',
                                           files=files)
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='child-job', result='SUCCESS', changes='3,1'),
            dict(name='child-job', result='SUCCESS', changes='4,1'),
        ], ordered=False)

    @simple_layout('layouts/file-matchers.yaml')
    def test_file_matchers(self):
        "Test several file matchers"
        files = {'parent1.txt': ''}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=files)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'parent2.txt': ''}
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B',
                                           files=files)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'child.txt': ''}
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C',
                                           files=files)
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'project.txt': ''}
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D',
                                           files=files)
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'tests/foo': ''}
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E',
                                           files=files)
        self.fake_gerrit.addEvent(E.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        files = {'tests/docs/foo': ''}
        F = self.fake_gerrit.addFakeChange('org/project', 'master', 'F',
                                           files=files)
        self.fake_gerrit.addEvent(F.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='child-job', result='SUCCESS', changes='2,1'),

            dict(name='child-override-job', result='SUCCESS', changes='3,1'),

            dict(name='project-override-job', result='SUCCESS', changes='4,1'),

            dict(name='irr-job', result='SUCCESS', changes='5,1'),
            dict(name='irr-override-job', result='SUCCESS', changes='5,1'),

            dict(name='irr-job', result='SUCCESS', changes='6,1'),
        ], ordered=False)

    def test_trusted_project_dep_on_non_live_untrusted_project(self):
        # Test we get a layout for trusted projects when they depend on
        # non live untrusted projects. This checks against a bug where
        # trusted project config changes can end up in a infinite loop
        # trying to find the right layout.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        files = {'zuul.yaml': ''}
        B = self.fake_gerrit.addFakeChange('common-config', 'master', 'B',
                                           files=files)
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-merge', result='SUCCESS', changes='1,1 2,1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1 2,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1 2,1'),
            dict(name='project1-project2-integration',
                 result='SUCCESS', changes='1,1 2,1'),
        ], ordered=False)


class TestAmbiguousProjectNames(ZuulTestCase):
    config_file = 'zuul-connections-multiple-gerrits.conf'
    tenant_config_file = 'config/ambiguous-names/main.yaml'

    def test_client_enqueue_canonical(self):
        "Test that the RPC client can enqueue a change using canonical name"
        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        A.addApproval('Approved', 1)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        self.addCleanup(client.shutdown)
        r = client.enqueue(tenant='tenant-one',
                           pipeline='check',
                           project='review.example.com/org/project',
                           trigger='gerrit',
                           change='1,1')
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(r, True)


class TestExecutor(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def assertFinalState(self):
        # In this test, we expect to shut down in a non-final state,
        # so skip these checks.
        pass

    def assertCleanShutdown(self):
        self.log.debug("Assert clean shutdown")

        # After shutdown, make sure no jobs are running
        self.assertEqual({}, self.executor_server.job_workers)

        # Make sure that git.Repo objects have been garbage collected.
        repos = []
        gc.collect()
        for obj in gc.get_objects():
            if isinstance(obj, git.Repo):
                self.log.debug("Leaked git repo object: %s" % repr(obj))
                repos.append(obj)
        self.assertEqual(len(repos), 0)

    def test_executor_shutdown(self):
        "Test that the executor can shut down with jobs running"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()


class TestDependencyGraph(ZuulTestCase):
    tenant_config_file = 'config/dependency-graph/main.yaml'

    def test_dependeny_graph_dispatch_jobs_once(self):
        "Test a job in a dependency graph is queued only once"
        # Job dependencies, starting with A
        #     A
        #    / \
        #   B   C
        #  / \ / \
        # D   F   E
        #     |
        #     G

        self.executor_server.hold_jobs_in_build = True
        change = self.fake_gerrit.addFakeChange(
            'org/project', 'master', 'change')
        change.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(change.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.assertEqual([b.name for b in self.builds], ['A'])

        self.executor_server.release('A')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['B', 'C'])

        self.executor_server.release('B')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['C', 'D'])

        self.executor_server.release('D')
        self.waitUntilSettled()
        self.assertEqual([b.name for b in self.builds], ['C'])

        self.executor_server.release('C')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['E', 'F'])

        self.executor_server.release('F')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['E', 'G'])

        self.executor_server.release('G')
        self.waitUntilSettled()
        self.assertEqual([b.name for b in self.builds], ['E'])

        self.executor_server.release('E')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 7)

        self.assertEqual(change.data['status'], 'MERGED')
        self.assertEqual(change.reported, 2)

    def test_jobs_launched_only_if_all_dependencies_are_successful(self):
        "Test that a job waits till all dependencies are successful"
        # Job dependencies, starting with A
        #     A
        #    / \
        #   B   C*
        #  / \ / \
        # D   F   E
        #     |
        #     G

        self.executor_server.hold_jobs_in_build = True
        change = self.fake_gerrit.addFakeChange(
            'org/project', 'master', 'change')
        change.addApproval('Code-Review', 2)

        self.executor_server.failJob('C', change)

        self.fake_gerrit.addEvent(change.addApproval('Approved', 1))

        self.waitUntilSettled()
        self.assertEqual([b.name for b in self.builds], ['A'])

        self.executor_server.release('A')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['B', 'C'])

        self.executor_server.release('B')
        self.waitUntilSettled()
        self.assertEqual(sorted(b.name for b in self.builds), ['C', 'D'])

        self.executor_server.release('D')
        self.waitUntilSettled()
        self.assertEqual([b.name for b in self.builds], ['C'])

        self.executor_server.release('C')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 4)

        self.assertEqual(change.data['status'], 'NEW')
        self.assertEqual(change.reported, 2)

    @simple_layout('layouts/soft-dependencies-error.yaml')
    def test_soft_dependencies_error(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([])
        self.assertEqual(len(A.messages), 1)
        self.assertTrue('Job project-merge not defined' in A.messages[0])
        print(A.messages)

    @simple_layout('layouts/soft-dependencies.yaml')
    def test_soft_dependencies(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertHistory([
            dict(name='deploy', result='SUCCESS', changes='1,1'),
        ], ordered=False)


class TestDuplicatePipeline(ZuulTestCase):
    tenant_config_file = 'config/duplicate-pipeline/main.yaml'

    def test_duplicate_pipelines(self):
        "Test that a change matching multiple pipelines works"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getChangeRestoredEvent())
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-test1', result='SUCCESS', changes='1,1',
                 pipeline='dup1'),
            dict(name='project-test1', result='SUCCESS', changes='1,1',
                 pipeline='dup2'),
        ], ordered=False)

        self.assertEqual(len(A.messages), 2)

        if 'dup1' in A.messages[0]:
            self.assertIn('dup1', A.messages[0])
            self.assertNotIn('dup2', A.messages[0])
            self.assertIn('project-test1', A.messages[0])
            self.assertIn('dup2', A.messages[1])
            self.assertNotIn('dup1', A.messages[1])
            self.assertIn('project-test1', A.messages[1])
        else:
            self.assertIn('dup1', A.messages[1])
            self.assertNotIn('dup2', A.messages[1])
            self.assertIn('project-test1', A.messages[1])
            self.assertIn('dup2', A.messages[0])
            self.assertNotIn('dup1', A.messages[0])
            self.assertIn('project-test1', A.messages[0])


class TestSchedulerRegexProject(ZuulTestCase):
    tenant_config_file = 'config/regex-project/main.yaml'

    def test_regex_project(self):
        "Test that changes are tested in parallel and merged in series"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        # We expect the following builds:
        #  - 1 for org/project
        #  - 3 for org/project1
        #  - 3 for org/project2
        self.assertEqual(len(self.history), 7)
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 1)

        self.assertHistory([
            dict(name='project-test', result='SUCCESS', changes='1,1'),
            dict(name='project-test1', result='SUCCESS', changes='2,1'),
            dict(name='project-common-test', result='SUCCESS', changes='2,1'),
            dict(name='project-common-test-canonical', result='SUCCESS',
                 changes='2,1'),
            dict(name='project-test2', result='SUCCESS', changes='3,1'),
            dict(name='project-common-test', result='SUCCESS', changes='3,1'),
            dict(name='project-common-test-canonical', result='SUCCESS',
                 changes='3,1'),
        ], ordered=False)


class TestSchedulerTemplatedProject(ZuulTestCase):
    tenant_config_file = 'config/templated-project/main.yaml'

    def test_job_from_templates_executed(self):
        "Test whether a job generated via a template can be executed"

        A = self.fake_gerrit.addFakeChange(
            'org/templated-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

    def test_layered_templates(self):
        "Test whether a job generated via a template can be executed"

        A = self.fake_gerrit.addFakeChange(
            'org/layered-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-test3'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-test4'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-foo-test5'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test6').result,
                         'SUCCESS')

    def test_unimplied_branch_matchers(self):
        # This tests that there are no implied branch matchers added
        # to project templates in unbranched projects.
        self.create_branch('org/layered-project', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/layered-project', 'stable'))
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange(
            'org/layered-project', 'stable', 'A')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.log.info(
            self.getJobFromHistory('project-test1').
            parameters['zuul']['_inheritance_path'])

    def test_implied_branch_matchers(self):
        # This tests that there is an implied branch matcher when a
        # template is used on an in-repo project pipeline definition.
        self.create_branch('untrusted-config', 'stable')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'untrusted-config', 'stable'))
        self.waitUntilSettled()

        A = self.fake_gerrit.addFakeChange(
            'untrusted-config', 'stable', 'A')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.log.info(
            self.getJobFromHistory('project-test1').
            parameters['zuul']['_inheritance_path'])

        # Now create a new branch named stable-foo and change the project
        # pipeline
        self.create_branch('untrusted-config', 'stable-foo')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'untrusted-config', 'stable-foo'))
        self.waitUntilSettled()

        in_repo_conf = textwrap.dedent(
            """
            - project:
                name: untrusted-config
                templates:
                  - test-three-and-four
            """)
        file_dict = {'zuul.d/project.yaml': in_repo_conf}
        B = self.fake_gerrit.addFakeChange('untrusted-config', 'stable-foo',
                                           'B', files=file_dict)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='project-test1', result='SUCCESS', changes='1,1'),
            dict(name='project-test2', result='SUCCESS', changes='1,1'),
            dict(name='layered-project-test3', result='SUCCESS',
                 changes='2,1'),
            dict(name='layered-project-test4', result='SUCCESS',
                 changes='2,1'),
        ], ordered=False)


class TestSchedulerSuccessURL(ZuulTestCase):
    tenant_config_file = 'config/success-url/main.yaml'

    def test_success_url(self):
        "Ensure bad build params are ignored"
        self.sched.reconfigure(self.config)
        self.init_repo('org/docs')

        A = self.fake_gerrit.addFakeChange('org/docs', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Both builds ran: docs-draft-test + docs-draft-test2
        self.assertEqual(len(self.history), 2)

        # Grab build id
        for build in self.history:
            if build.name == 'docs-draft-test':
                uuid = build.uuid[:7]
            elif build.name == 'docs-draft-test2':
                uuid_test2 = build.uuid

        # Two msgs: 'Starting...'  + results
        self.assertEqual(len(self.smtp_messages), 2)
        body = self.smtp_messages[1]['body'].splitlines()
        self.assertEqual('Build succeeded.', body[0])

        self.assertIn(
            '- docs-draft-test http://docs-draft.example.org/1/1/1/check/'
            'docs-draft-test/%s/publish-docs/' % uuid,
            body[2])

        # NOTE: This default URL is currently hard-coded in executor/server.py
        self.assertIn(
            '- docs-draft-test2 finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=uuid_test2),
            body[3])


class TestSchedulerMerges(ZuulTestCase):
    tenant_config_file = 'config/merges/main.yaml'

    def _test_project_merge_mode(self, mode):
        self.executor_server.keep_jobdir = False
        project = 'org/project-%s' % mode
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        B = self.fake_gerrit.addFakeChange(project, 'master', 'B')
        C = self.fake_gerrit.addFakeChange(project, 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        build = self.builds[-1]
        path = os.path.join(build.jobdir.src_root, 'review.example.com',
                            project)
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits()]
        repo_messages.reverse()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        return repo_messages

    def _test_merge(self, mode):
        us_path = 'file://' + os.path.join(
            self.upstream_root, 'org/project-%s' % mode)
        expected_messages = [
            'initial commit',
            'add content from fixture',
            # the intermediate commits order is nondeterministic
            "Merge commit 'refs/changes/1/2/1' of %s into HEAD" % us_path,
            "Merge commit 'refs/changes/1/3/1' of %s into HEAD" % us_path,
        ]
        result = self._test_project_merge_mode(mode)
        self.assertEqual(result[:2], expected_messages[:2])
        self.assertEqual(result[-2:], expected_messages[-2:])

    def test_project_merge_mode_merge(self):
        self._test_merge('merge')

    def test_project_merge_mode_merge_resolve(self):
        self._test_merge('merge-resolve')

    def test_project_merge_mode_cherrypick(self):
        expected_messages = [
            'initial commit',
            'add content from fixture',
            'A-1',
            'B-1',
            'C-1']
        result = self._test_project_merge_mode('cherry-pick')
        self.assertEqual(result, expected_messages)

    def test_merge_branch(self):
        "Test that the right commits are on alternate branches"
        self.create_branch('org/project-merge-branches', 'mp')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project-merge-branches', 'mp'))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'mp', 'A')
        B = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'mp', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        build = self.builds[-1]
        self.assertEqual(build.parameters['zuul']['branch'], 'mp')
        path = os.path.join(build.jobdir.src_root, 'review.example.com',
                            'org/project-merge-branches')
        repo = git.Repo(path)

        repo_messages = [c.message.strip() for c in repo.iter_commits()]
        repo_messages.reverse()
        correct_messages = [
            'initial commit',
            'add content from fixture',
            'mp commit',
            'A-1', 'B-1', 'C-1']
        self.assertEqual(repo_messages, correct_messages)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_merge_multi_branch(self):
        "Test that dependent changes on multiple branches are merged"
        self.create_branch('org/project-merge-branches', 'mp')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project-merge-branches', 'mp'))
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'master', 'A')
        B = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange(
            'org/project-merge-branches', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        job_A = None
        for job in self.builds:
            if 'project-merge' in job.name:
                job_A = job

        path = os.path.join(job_A.jobdir.src_root, 'review.example.com',
                            'org/project-merge-branches')
        repo = git.Repo(path)
        repo_messages = [c.message.strip()
                         for c in repo.iter_commits()]
        repo_messages.reverse()
        correct_messages = [
            'initial commit', 'add content from fixture', 'A-1']
        self.assertEqual(repo_messages, correct_messages)

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        job_B = None
        for job in self.builds:
            if 'project-merge' in job.name:
                job_B = job

        path = os.path.join(job_B.jobdir.src_root, 'review.example.com',
                            'org/project-merge-branches')
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits()]
        repo_messages.reverse()
        correct_messages = [
            'initial commit', 'add content from fixture', 'mp commit', 'B-1']
        self.assertEqual(repo_messages, correct_messages)

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        job_C = None
        for job in self.builds:
            if 'project-merge' in job.name:
                job_C = job

        path = os.path.join(job_C.jobdir.src_root, 'review.example.com',
                            'org/project-merge-branches')
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits()]

        repo_messages.reverse()
        correct_messages = [
            'initial commit', 'add content from fixture',
            'A-1', 'C-1']
        # Ensure the right commits are in the history for this ref
        self.assertEqual(repo_messages, correct_messages)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()


class TestSemaphore(ZuulTestCase):
    tenant_config_file = 'config/semaphore/main.yaml'

    def test_semaphore_one(self):
        "Test semaphores with max=1 (mutex)"
        tenant = self.sched.abide.tenants.get('tenant-one')

        self.executor_server.hold_jobs_in_build = True

        # Pause nodepool so we can check the ordering of getting the nodes
        # and aquiring the semaphore.
        self.fake_nodepool.paused = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # By default we first lock the semaphore and then get the nodes
        # so at this point the semaphore needs to be aquired.
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)
        self.fake_nodepool.paused = False
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'semaphore-one-test1')
        self.assertEqual(self.builds[2].name, 'project-test1')

        self.executor_server.release('semaphore-one-test1')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-one-test2')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.executor_server.release('semaphore-one-test2')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-one-test1')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.executor_server.release('semaphore-one-test1')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-one-test2')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.executor_server.release('semaphore-one-test2')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

    def test_semaphore_two(self):
        "Test semaphores with max>1"
        tenant = self.sched.abide.tenants.get('tenant-one')

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        self.assertFalse('test-semaphore-two' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'semaphore-two-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-two-test2')
        self.assertEqual(self.builds[3].name, 'project-test1')
        self.assertTrue('test-semaphore-two' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore-two', [])), 2)

        self.executor_server.release('semaphore-two-test1')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'semaphore-two-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'semaphore-two-test1')
        self.assertTrue('test-semaphore-two' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore-two', [])), 2)

        self.executor_server.release('semaphore-two-test2')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-two-test1')
        self.assertEqual(self.builds[3].name, 'semaphore-two-test2')
        self.assertTrue('test-semaphore-two' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore-two', [])), 2)

        self.executor_server.release('semaphore-two-test1')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name, 'semaphore-two-test2')
        self.assertTrue('test-semaphore-two' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore-two', [])), 1)

        self.executor_server.release('semaphore-two-test2')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertFalse('test-semaphore-two' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)

    def test_semaphore_node_failure(self):
        "Test semaphore and node failure"
        tenant = self.sched.abide.tenants.get('tenant-one')

        # Pause nodepool so we can fail the node request later
        self.fake_nodepool.pause()

        A = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # By default we first lock the semaphore and then get the nodes
        # so at this point the semaphore needs to be aquired.
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        # Fail the node request and unpause
        req = self.fake_nodepool.getNodeRequests()[0]
        self.fake_nodepool.addFailRequest(req)
        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        # At this point the job that holds the semaphore failed with
        # node_failure and the semaphore must be released.
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)
        self.assertEquals(1, A.reported)
        self.assertIn('semaphore-one-test3 semaphore-one-test3 : NODE_FAILURE',
                      A.messages[0])

    def test_semaphore_resources_first(self):
        "Test semaphores with max=1 (mutex) and get resources first"
        tenant = self.sched.abide.tenants.get('tenant-one')

        self.executor_server.hold_jobs_in_build = True

        # Pause nodepool so we can check the ordering of getting the nodes
        # and aquiring the semaphore.
        self.fake_nodepool.paused = True

        A = self.fake_gerrit.addFakeChange('org/project3', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project3', 'master', 'B')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Here we first get the resources and then lock the semaphore
        # so at this point the semaphore should not be aquired.
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)
        self.fake_nodepool.paused = False
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name,
                         'semaphore-one-test1-resources-first')
        self.assertEqual(self.builds[2].name, 'project-test1')

        self.executor_server.release('semaphore-one-test1')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test1')
        self.assertEqual(self.builds[2].name,
                         'semaphore-one-test2-resources-first')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_semaphore_resources_first_node_failure(self):
        "Test semaphore and node failure"
        tenant = self.sched.abide.tenants.get('tenant-one')

        # Pause nodepool so we can fail the node request later
        self.fake_nodepool.pause()

        A = self.fake_gerrit.addFakeChange('org/project4', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # With resources first we first get the nodes so at this point the
        # semaphore must not be aquired.
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        # Fail the node request and unpause
        req = self.fake_nodepool.getNodeRequests()[0]
        self.fake_nodepool.addFailRequest(req)
        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        # At this point the job should never have acuired a semaphore so check
        # that it still has not locked a semaphore.
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)
        self.assertEquals(1, A.reported)
        self.assertIn('semaphore-one-test1-resources-first : NODE_FAILURE',
                      A.messages[0])

    def test_semaphore_zk_error(self):
        "Test semaphore release with zk error"
        tenant = self.sched.abide.tenants.get('tenant-one')

        A = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        # Simulate a single zk error in useNodeSet
        orig_useNodeSet = self.nodepool.useNodeSet

        def broken_use_nodeset(nodeset):
            # restore original useNodeSet
            self.nodepool.useNodeSet = orig_useNodeSet
            raise NoNodeError()

        self.nodepool.useNodeSet = broken_use_nodeset

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        # cleanup the queue
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

    def test_semaphore_abandon(self):
        "Test abandon with job semaphores"
        self.executor_server.hold_jobs_in_build = True
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        # The check pipeline should be empty
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_semaphore_abandon_pending_node_request(self):
        "Test abandon with job semaphores and pending node request"
        self.executor_server.hold_jobs_in_build = True

        # Pause nodepool so we can check the ordering of getting the nodes
        # and aquiring the semaphore.
        self.fake_nodepool.paused = True

        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        # The check pipeline should be empty
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.fake_nodepool.paused = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_semaphore_abandon_pending_execution(self):
        "Test abandon with job semaphores and pending job execution"

        # Pause the executor so it doesn't take any jobs.
        self.executor_server.pause()

        # Pause nodepool so we can wait on the node requests and fulfill them
        # in a controlled manner.
        self.fake_nodepool.paused = True

        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(self.nodepool.requests), 2)

        # Now unpause nodepool to fulfill the node requests. We cannot use
        # waitUntilSettled here because the executor is paused.
        self.fake_nodepool.paused = False
        for _ in iterate_timeout(30, 'fulfill node requests'):
            if len(self.nodepool.requests) == 0:
                break

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        # The check pipeline should be empty
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.release()
        self.waitUntilSettled()

    def test_semaphore_new_patchset(self):
        "Test new patchset with job semaphores"
        self.executor_server.hold_jobs_in_build = True
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)
        semaphore = tenant.semaphore_handler.semaphores['test-semaphore']
        self.assertEqual(len(semaphore), 1)

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)
        semaphore = tenant.semaphore_handler.semaphores['test-semaphore']
        self.assertEqual(len(semaphore), 1)

        items = check_pipeline.getAllItems()
        self.assertEqual(items[0].change.number, '1')
        self.assertEqual(items[0].change.patchset, '2')
        self.assertTrue(items[0].live)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

    def test_semaphore_reconfigure(self):
        "Test reconfigure with job semaphores"
        self.executor_server.hold_jobs_in_build = True
        tenant = self.sched.abide.tenants.get('tenant-one')
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        # reconfigure without layout change
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        tenant = self.sched.abide.tenants.get('tenant-one')

        # semaphore still must be held
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.commitConfigUpdate(
            'common-config',
            'config/semaphore/zuul-reconfiguration.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        tenant = self.sched.abide.tenants.get('tenant-one')

        self.executor_server.release('project-test1')
        self.waitUntilSettled()

        # There should be no builds anymore
        self.assertEqual(len(self.builds), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

    def test_semaphore_reconfigure_job_removal(self):
        "Test job removal during reconfiguration with semaphores"
        self.executor_server.hold_jobs_in_build = True
        tenant = self.sched.abide.tenants.get('tenant-one')

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.commitConfigUpdate(
            'common-config',
            'config/semaphore/git/common-config/zuul-remove-job.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        # Release job project-test1 which should be the only job left
        self.executor_server.release('project-test1')
        self.waitUntilSettled()

        # The check pipeline should be empty
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_semaphore_reconfigure_job_removal_pending_node_request(self):
        """
        Test job removal during reconfiguration with semaphores and pending
        node request.
        """
        self.executor_server.hold_jobs_in_build = True

        # Pause nodepool so we can block the job in node request state during
        # reconfiguration.
        self.fake_nodepool.pause()

        tenant = self.sched.abide.tenants.get('tenant-one')

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)

        self.commitConfigUpdate(
            'common-config',
            'config/semaphore/git/common-config/zuul-remove-job.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        # Now we can unpause nodepool
        self.fake_nodepool.unpause()
        self.waitUntilSettled()

        # Release job project-test1 which should be the only job left
        self.executor_server.release('project-test1')
        self.waitUntilSettled()

        # The check pipeline should be empty
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']
        items = check_pipeline.getAllItems()
        self.assertEqual(len(items), 0)

        # The semaphore should be released
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()


class TestSemaphoreMultiTenant(ZuulTestCase):
    tenant_config_file = 'config/multi-tenant-semaphore/main.yaml'

    def test_semaphore_tenant_isolation(self):
        "Test semaphores in multiple tenants"

        self.waitUntilSettled()
        tenant_one = self.sched.abide.tenants.get('tenant-one')
        tenant_two = self.sched.abide.tenants.get('tenant-two')

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project2', 'master', 'E')
        self.assertFalse('test-semaphore' in
                         tenant_one.semaphore_handler.semaphores)
        self.assertFalse('test-semaphore' in
                         tenant_two.semaphore_handler.semaphores)

        # add patches to project1 of tenant-one
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # one build of project1-test1 must run
        # semaphore of tenant-one must be acquired once
        # semaphore of tenant-two must not be acquired
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project1-test1')
        self.assertTrue('test-semaphore' in
                        tenant_one.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_one.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)
        self.assertFalse('test-semaphore' in
                         tenant_two.semaphore_handler.semaphores)

        # add patches to project2 of tenant-two
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(D.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(E.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # one build of project1-test1 must run
        # two builds of project2-test1 must run
        # semaphore of tenant-one must be acquired once
        # semaphore of tenant-two must be acquired twice
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project1-test1')
        self.assertEqual(self.builds[1].name, 'project2-test1')
        self.assertEqual(self.builds[2].name, 'project2-test1')
        self.assertTrue('test-semaphore' in
                        tenant_one.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_one.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)
        self.assertTrue('test-semaphore' in
                        tenant_two.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_two.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 2)

        self.executor_server.release('project1-test1')
        self.waitUntilSettled()

        # one build of project1-test1 must run
        # two builds of project2-test1 must run
        # semaphore of tenant-one must be acquired once
        # semaphore of tenant-two must be acquired twice
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project2-test1')
        self.assertEqual(self.builds[1].name, 'project2-test1')
        self.assertEqual(self.builds[2].name, 'project1-test1')
        self.assertTrue('test-semaphore' in
                        tenant_one.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_one.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)
        self.assertTrue('test-semaphore' in
                        tenant_two.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_two.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 2)

        self.executor_server.release('project2-test1')
        self.waitUntilSettled()

        # one build of project1-test1 must run
        # one build of project2-test1 must run
        # semaphore of tenant-one must be acquired once
        # semaphore of tenant-two must be acquired once
        self.assertEqual(len(self.builds), 2)
        self.assertTrue('test-semaphore' in
                        tenant_one.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_one.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)
        self.assertTrue('test-semaphore' in
                        tenant_two.semaphore_handler.semaphores)
        self.assertEqual(len(tenant_two.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()

        # no build must run
        # semaphore of tenant-one must not be acquired
        # semaphore of tenant-two must not be acquired
        self.assertEqual(len(self.builds), 0)
        self.assertFalse('test-semaphore' in
                         tenant_one.semaphore_handler.semaphores)
        self.assertFalse('test-semaphore' in
                         tenant_two.semaphore_handler.semaphores)

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)


class TestImplicitProject(ZuulTestCase):
    tenant_config_file = 'config/implicit-project/main.yaml'

    def test_implicit_project(self):
        # config project should work with implicit project name
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        # untrusted project should work with implicit project name
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        self.assertHistory([
            dict(name='test-common', result='SUCCESS', changes='1,1'),
            dict(name='test-common', result='SUCCESS', changes='2,1'),
            dict(name='test-project', result='SUCCESS', changes='2,1'),
        ], ordered=False)

        # now test adding a further project in repo
        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: test-project
                run: playbooks/test-project.yaml
            - job:
                name: test2-project
                run: playbooks/test-project.yaml

            - project:
                check:
                  jobs:
                    - test-project
                gate:
                  jobs:
                    - test-project

            - project:
                check:
                  jobs:
                    - test2-project
                gate:
                  jobs:
                    - test2-project

            """)
        file_dict = {'.zuul.yaml': in_repo_conf}
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        # change C must be merged
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)
        self.assertHistory([
            dict(name='test-common', result='SUCCESS', changes='1,1'),
            dict(name='test-common', result='SUCCESS', changes='2,1'),
            dict(name='test-project', result='SUCCESS', changes='2,1'),
            dict(name='test-common', result='SUCCESS', changes='3,1'),
            dict(name='test-project', result='SUCCESS', changes='3,1'),
            dict(name='test2-project', result='SUCCESS', changes='3,1'),
        ], ordered=False)


class TestSemaphoreInRepo(ZuulTestCase):
    config_file = 'zuul-connections-gerrit-and-github.conf'
    tenant_config_file = 'config/in-repo/main.yaml'

    def test_semaphore_in_repo(self):
        "Test semaphores in repo config"

        # This tests dynamic semaphore handling in project repos. The semaphore
        # max value should not be evaluated dynamically but must be updated
        # after the change lands.

        self.waitUntilSettled()
        tenant = self.sched.abide.tenants.get('tenant-one')

        in_repo_conf = textwrap.dedent(
            """
            - job:
                name: project-test1

            - job:
                name: project-test2
                run: playbooks/project-test2.yaml
                semaphore: test-semaphore

            - project:
                name: org/project
                tenant-one-gate:
                  jobs:
                    - project-test2

            # the max value in dynamic layout must be ignored
            - semaphore:
                name: test-semaphore
                max: 2
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
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        B.setDependsOn(A, 1)
        C.setDependsOn(A, 1)

        self.executor_server.hold_jobs_in_build = True

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.waitUntilSettled()

        # check that the layout in a queue item still has max value of 1
        # for test-semaphore
        pipeline = tenant.layout.pipelines.get('tenant-one-gate')
        queue = None
        for queue_candidate in pipeline.queues:
            if queue_candidate.name == 'org/project':
                queue = queue_candidate
                break
        queue_item = queue.queue[0]
        item_dynamic_layout = queue_item.layout
        dynamic_test_semaphore = \
            item_dynamic_layout.semaphores.get('test-semaphore')
        self.assertEqual(dynamic_test_semaphore.max, 1)

        # one build must be in queue, one semaphores acquired
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-test2')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 1)

        self.executor_server.release('project-test2')
        self.waitUntilSettled()

        # change A must be merged
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

        # send change-merged event as the gerrit mock doesn't send it
        self.fake_gerrit.addEvent(A.getChangeMergedEvent())
        self.waitUntilSettled()

        # now that change A was merged, the new semaphore max must be effective
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(tenant.layout.semaphores.get('test-semaphore').max, 2)

        # two builds must be in queue, two semaphores acquired
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test2')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue('test-semaphore' in
                        tenant.semaphore_handler.semaphores)
        self.assertEqual(len(tenant.semaphore_handler.semaphores.get(
            'test-semaphore', [])), 2)

        self.executor_server.release('project-test2')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertFalse('test-semaphore' in
                         tenant.semaphore_handler.semaphores)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)


class TestSchedulerBranchMatcher(ZuulTestCase):

    @simple_layout('layouts/matcher-test.yaml')
    def test_job_branch_ignored(self):
        '''
        Test that branch matching logic works.

        The 'ignore-branch' job has a branch matcher that is supposed to
        match every branch except for the 'featureA' branch, so it should
        not be run on a change to that branch.
        '''
        self.create_branch('org/project', 'featureA')
        self.fake_gerrit.addEvent(
            self.fake_gerrit.getFakeBranchCreatedEvent(
                'org/project', 'featureA'))
        self.waitUntilSettled()
        A = self.fake_gerrit.addFakeChange('org/project', 'featureA', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.printHistory()
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertJobNotInHistory('ignore-branch')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertIn('gate', A.messages[1],
                      "A should transit gate")
