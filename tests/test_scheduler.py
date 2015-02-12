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
import logging
import os
import re
import shutil
import time
import urllib
import urllib2
import yaml

import git
import testtools

import zuul.change_matcher
import zuul.scheduler
import zuul.rpcclient
import zuul.reporter.gerrit
import zuul.reporter.smtp

from tests.base import (
    BaseTestCase,
    ZuulTestCase,
    repack_repo,
)

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


class TestSchedulerConfigParsing(BaseTestCase):

    def test_parse_skip_if(self):
        job_yaml = """
jobs:
  - name: job_name
    skip-if:
      - project: ^project_name$
        branch: ^stable/icehouse$
        all-files-match-any:
          - ^filename$
      - project: ^project2_name$
        all-files-match-any:
          - ^filename2$
    """.strip()
        data = yaml.load(job_yaml)
        config_job = data.get('jobs')[0]
        sched = zuul.scheduler.Scheduler()
        cm = zuul.change_matcher
        expected = cm.MatchAny([
            cm.MatchAll([
                cm.ProjectMatcher('^project_name$'),
                cm.BranchMatcher('^stable/icehouse$'),
                cm.MatchAllFiles([cm.FileMatcher('^filename$')]),
            ]),
            cm.MatchAll([
                cm.ProjectMatcher('^project2_name$'),
                cm.MatchAllFiles([cm.FileMatcher('^filename2$')]),
            ]),
        ])
        matcher = sched._parseSkipIf(config_job)
        self.assertEqual(expected, matcher)


class TestScheduler(ZuulTestCase):

    def test_jobs_launched(self):
        "Test that jobs are launched and a change is merged"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

        self.assertReportedStat('gerrit.event.comment-added', value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.current_changes',
                                value='1|g')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.resident_time', kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.total_changes',
                                value='1|c')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.resident_time', kind='ms')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.total_changes', value='1|c')

    def test_initial_pipeline_gauges(self):
        "Test that each pipeline reported its length on start"
        pipeline_names = self.sched.layout.pipelines.keys()
        self.assertNotEqual(len(pipeline_names), 0)
        for name in pipeline_names:
            self.assertReportedStat('zuul.pipeline.%s.current_changes' % name,
                                    value='0|g')

    def test_duplicate_pipelines(self):
        "Test that a change matching multiple pipelines works"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getChangeRestoredEvent())
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)
        self.history[0].name == 'project-test1'
        self.history[1].name == 'project-test1'

        self.assertEqual(len(A.messages), 2)
        if 'dup1/project-test1' in A.messages[0]:
            self.assertIn('dup1/project-test1', A.messages[0])
            self.assertNotIn('dup2/project-test1', A.messages[0])
            self.assertNotIn('dup1/project-test1', A.messages[1])
            self.assertIn('dup2/project-test1', A.messages[1])
        else:
            self.assertIn('dup1/project-test1', A.messages[1])
            self.assertNotIn('dup2/project-test1', A.messages[1])
            self.assertNotIn('dup1/project-test1', A.messages[0])
            self.assertIn('dup2/project-test1', A.messages[0])

    def test_parallel_changes(self):
        "Test that changes are tested in parallel and merged in series"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))
        self.assertEqual(self.builds[2].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[3], A, B))

        self.assertEqual(self.builds[4].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[4], A, B, C))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[3], A, B))

        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[4], A, B, C))
        self.assertEqual(self.builds[5].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[5], A, B, C))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()

        self.waitUntilSettled()
        # It's certain that the merge job for change 2 will run, but
        # the test1 and test2 jobs may or may not run.
        self.assertTrue(len(self.history) > 6)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

    def test_independent_queues(self):
        "Test that changes end up in the right queues"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        # There should be one merge job at the head of each queue running
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project1-merge')
        self.assertTrue(self.job_has_changes(self.builds[1], B))

        # Release the current merge builds
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        # Release the merge job for project2 which is behind project1
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # All the test builds should be running:
        # project1 (3) + project2 (3) + project (2) = 8
        self.assertEqual(len(self.builds), 8)

        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(len(self.history), 11)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_at_head(self):
        "Test that if a change at the head fails, jobs behind it are canceled"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
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

        # project-test2, project-merge for B
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 4)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 15)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_in_middle(self):
        "Test a failed change in the middle of the queue"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
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

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # project-test1 and project-test2 for A
        # project-test2 for B
        # project-test1 and project-test2 for C
        self.assertEqual(len(self.builds), 5)

        items = self.sched.layout.pipelines['gate'].getAllItems()
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

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].name, 'build:project-merge')
        self.assertTrue(self.job_has_changes(queue[0], A))

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 6)
        self.assertEqual(queue[0].name, 'build:project-test1')
        self.assertEqual(queue[1].name, 'build:project-test2')
        self.assertEqual(queue[2].name, 'build:project-test1')
        self.assertEqual(queue[3].name, 'build:project-test2')
        self.assertEqual(queue[4].name, 'build:project-test1')
        self.assertEqual(queue[5].name, 'build:project-test2')

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

    def test_two_failed_changes_at_head(self):
        "Test that changes are reparented correctly if 2 fail at head"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)
        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertTrue(self.job_has_changes(self.builds[2], A))
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[4], A))
        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))

        # Fail change B first
        self.release(self.builds[2])
        self.waitUntilSettled()

        # restart of C after B failure
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test2')
        self.assertEqual(self.builds[3].name, 'project-test1')
        self.assertEqual(self.builds[4].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[1], A))
        self.assertTrue(self.job_has_changes(self.builds[2], A))
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[4], A))
        self.assertFalse(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))

        # Finish running all passing jobs for change A
        self.release(self.builds[1])
        self.waitUntilSettled()
        # Fail and report change A
        self.release(self.builds[0])
        self.waitUntilSettled()

        # restart of B,C after A failure
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')  # B
        self.assertEqual(self.builds[1].name, 'project-test2')  # B
        self.assertEqual(self.builds[2].name, 'project-test1')  # C
        self.assertEqual(self.builds[3].name, 'project-test2')  # C

        self.assertFalse(self.job_has_changes(self.builds[1], A))
        self.assertTrue(self.job_has_changes(self.builds[1], B))
        self.assertFalse(self.job_has_changes(self.builds[1], C))

        self.assertFalse(self.job_has_changes(self.builds[2], A))
        # After A failed and B and C restarted, B should be back in
        # C's tests because it has not failed yet.
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

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

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')

        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

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

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)
        F.addApproval('CRVW', 2)
        G.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

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
        source = self.sched.layout.pipelines['gate'].source
        source.maintainCache([])

        self.worker.hold_jobs_in_build = True
        A.addApproval('APRV', 1)
        B.addApproval('APRV', 1)
        D.addApproval('APRV', 1)
        E.addApproval('APRV', 1)
        F.addApproval('APRV', 1)
        G.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        for x in range(8):
            self.worker.release('.*-merge')
            self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.worker.release()
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

    def test_trigger_cache(self):
        "Test that the trigger cache operates correctly"
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        X = self.fake_gerrit.addFakeChange('org/project', 'master', 'X')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(X.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        for build in self.builds:
            if build.parameters['ZUUL_PIPELINE'] == 'check':
                build.release()
        self.waitUntilSettled()
        for build in self.builds:
            if build.parameters['ZUUL_PIPELINE'] == 'check':
                build.release()
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.log.debug("len %s" % self.gerrit._change_cache.keys())
        # there should still be changes in the cache
        self.assertNotEqual(len(self.gerrit._change_cache.keys()), 0)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.queried, 2)  # Initial and isMerged
        self.assertEqual(B.queried, 3)  # Initial A, refresh from B, isMerged

    def test_can_merge(self):
        "Test whether a change is ready to merge"
        # TODO: move to test_gerrit (this is a unit test!)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        source = self.sched.layout.pipelines['gate'].source
        a = source._getChange(1, 2)
        mgr = self.sched.layout.pipelines['gate'].manager
        self.assertFalse(source.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('CRVW', 2)
        a = source._getChange(1, 2, refresh=True)
        self.assertFalse(source.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('APRV', 1)
        a = source._getChange(1, 2, refresh=True)
        self.assertTrue(source.canMerge(a, mgr.getSubmitAllowNeeds()))
        source.maintainCache([])

    def test_build_configuration(self):
        "Test that zuul merges the right commits for testing"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'B-1', 'C-1']
        self.assertEqual(repo_messages, correct_messages)

    def test_build_configuration_conflict(self):
        "Test that merge conflicts are handled"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'A')
        A.addPatchset(['conflict'])
        B = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'B')
        B.addPatchset(['conflict'])
        C = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 1)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)  # A and C merge jobs

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 6)

    def test_post(self):
        "Test that post jobs run"

        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "d479a0bfcb34da57a31adb2a595c0cf687812543",
                "refName": "master",
                "project": "org/project",
            }
        }
        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 1)
        self.assertIn('project-post', job_names)

    def test_build_configuration_branch(self):
        "Test that the right commits are on alternate branches"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'mp', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'mp', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'A-1', 'B-1', 'C-1']
        self.assertEqual(repo_messages, correct_messages)

    def test_build_configuration_branch_interaction(self):
        "Test that switching between branches works"
        self.test_build_configuration()
        self.test_build_configuration_branch()
        # C has been merged, undo that
        path = os.path.join(self.upstream_root, "org/project")
        repo = git.Repo(path)
        repo.heads.master.commit = repo.commit('init')
        self.test_build_configuration()

    def test_build_configuration_multi_branch(self):
        "Test that dependent changes on multiple branches are merged"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        job_A = None
        for job in queue:
            if 'project-merge' in job.name:
                job_A = job
        ref_A = self.getParameter(job_A, 'ZUUL_REF')
        commit_A = self.getParameter(job_A, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change A: %s" % ref_A)
        self.log.debug("Got Zuul commit for change A: %s" % commit_A)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        job_B = None
        for job in queue:
            if 'project-merge' in job.name:
                job_B = job
        ref_B = self.getParameter(job_B, 'ZUUL_REF')
        commit_B = self.getParameter(job_B, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change B: %s" % ref_B)
        self.log.debug("Got Zuul commit for change B: %s" % commit_B)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        for job in queue:
            if 'project-merge' in job.name:
                job_C = job
        ref_C = self.getParameter(job_C, 'ZUUL_REF')
        commit_C = self.getParameter(job_C, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change C: %s" % ref_C)
        self.log.debug("Got Zuul commit for change C: %s" % commit_C)
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_C)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_C)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'C-1']
        # Ensure the right commits are in the history for this ref
        self.assertEqual(repo_messages, correct_messages)
        # Ensure ZUUL_REF -> ZUUL_COMMIT
        self.assertEqual(repo_shas[0], commit_C)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_B)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_B)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'B-1']
        self.assertEqual(repo_messages, correct_messages)
        self.assertEqual(repo_shas[0], commit_B)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_A)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_A)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1']
        self.assertEqual(repo_messages, correct_messages)
        self.assertEqual(repo_shas[0], commit_A)

        self.assertNotEqual(ref_A, ref_B, ref_C)
        self.assertNotEqual(commit_A, commit_B, commit_C)

    def test_one_job_project(self):
        "Test that queueing works with one job"
        A = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_job_from_templates_launched(self):
        "Test whether a job generated via a template can be launched"

        A = self.fake_gerrit.addFakeChange(
            'org/templated-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

    def test_layered_templates(self):
        "Test whether a job generated via a template can be launched"

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

    def test_dependent_changes_dequeue(self):
        "Test that dependent patches are not needlessly tested"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        # C -> B -> A -> M1

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.worker.addFailTest('project-merge', A)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 1)

    def test_failing_dependent_changes(self):
        "Test that failing dependent patches are taken out of stream"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)

        # E, D -> C -> B, A

        D.setDependsOn(C, 1)
        C.setDependsOn(B, 1)

        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        for build in self.builds:
            if build.parameters['ZUUL_CHANGE'] != '1':
                build.release()
                self.waitUntilSettled()

        self.worker.release()
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

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project1-test1', A)
        self.worker.addFailTest('project1-test2', A)
        self.worker.addFailTest('project1-project2-integration', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project1-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 9)
        self.assertEqual(self.builds[0].name, 'project1-test1')
        self.assertEqual(self.builds[1].name, 'project1-test2')
        self.assertEqual(self.builds[2].name, 'project1-project2-integration')
        self.assertEqual(self.builds[3].name, 'project1-test1')
        self.assertEqual(self.builds[4].name, 'project1-test2')
        self.assertEqual(self.builds[5].name, 'project1-project2-integration')
        self.assertEqual(self.builds[6].name, 'project1-test1')
        self.assertEqual(self.builds[7].name, 'project1-test2')
        self.assertEqual(self.builds[8].name, 'project1-project2-integration')

        self.release(self.builds[0])
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)  # test2,integration, merge for B
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 6)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 20)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_nonvoting_job(self):
        "Test that non-voting jobs don't vote."

        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('nonvoting-project-test2', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

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
        self.worker.addFailTest('project-test2', A)
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

    def test_dependent_behind_dequeue(self):
        "test that dependent changes behind dequeued changes work"
        # This complicated test is a reproduction of a real life bug
        self.sched.reconfigure(self.config)

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project2', 'master', 'E')
        F = self.fake_gerrit.addFakeChange('org/project3', 'master', 'F')
        D.setDependsOn(C, 1)
        E.setDependsOn(D, 1)
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)
        F.addApproval('CRVW', 2)

        A.fail_merge = True

        # Change object re-use in the gerrit trigger is hidden if
        # changes are added in quick succession; waiting makes it more
        # like real life.
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(F.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
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

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
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
        self.worker.build_history = []

        path = os.path.join(self.git_root, "org/project")
        print repack_repo(path)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
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
        # https://bugs.launchpad.net/zuul/+bug/1078946
        # This test assumes the repo is already cloned; make sure it is
        url = self.sched.triggers['gerrit'].getGitUrl(
            self.sched.layout.projects['org/project1'])
        self.merge_server.merger.addProject('org/project1', url)
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addPatchset(large=True)
        path = os.path.join(self.upstream_root, "org/project1")
        print repack_repo(path)
        path = os.path.join(self.git_root, "org/project1")
        print repack_repo(path)

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project1-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project1-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project1-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_nonexistent_job(self):
        "Test launching a job that doesn't exist"
        # Set to the state immediately after a restart
        self.resetGearmanServer()
        self.launcher.negative_function_cache_ttl = 0

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        # There may be a thread about to report a lost change
        while A.reported < 2:
            self.waitUntilSettled()
        job_names = [x.name for x in self.history]
        self.assertFalse(job_names)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEmptyQueues()

        # Make sure things still work:
        self.registerJobs()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_single_nonexistent_post_job(self):
        "Test launching a single post job that doesn't exist"
        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "d479a0bfcb34da57a31adb2a595c0cf687812543",
                "refName": "master",
                "project": "org/project",
            }
        }
        # Set to the state immediately after a restart
        self.resetGearmanServer()
        self.launcher.negative_function_cache_ttl = 0

        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 0)

    def test_new_patchset_dequeues_old(self):
        "Test that a new patchset causes the old to be dequeued"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.worker.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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

        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        check_pipeline = self.sched.layout.pipelines['check']

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
        self.worker.hold_jobs_in_build = False
        self.worker.release()
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

        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1, "One job being built (on hold)")
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.fake_gerrit.addEvent(A.getChangeAbandonedEvent())
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0, "No job running")
        self.assertEqual(len(self.history), 1, "Only one build in history")
        self.assertEqual(self.history[0].result, 'ABORTED',
                         "Build should have been aborted")
        self.assertEqual(A.reported, 1,
                         "Abandoned gate change should report only start")

    def test_abandoned_check(self):
        "Test that an abandoned change is dequeued from check"

        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        check_pipeline = self.sched.layout.pipelines['check']

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

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 4)
        self.assertEqual(self.history[0].result, 'ABORTED',
                         'Build should have been aborted')
        self.assertEqual(A.reported, 0, "Abandoned change should not report")
        self.assertEqual(B.reported, 1, "Change should report")

    def test_zuul_url_return(self):
        "Test if ZUUL_URL is returning when zuul_url is set in zuul.conf"
        self.assertTrue(self.sched.config.has_option('merger', 'zuul_url'))
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        for build in self.builds:
            self.assertTrue('ZUUL_URL' in build.parameters)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_new_patchset_dequeues_old_on_head(self):
        "Test that a new patchset causes the old to be dequeued (at head)"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.worker.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        self.worker.hold_jobs_in_build = True
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

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 1)
        self.assertEqual(len(self.history), 10)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

    def test_noop_job(self):
        "Test that the internal noop job works"
        A = self.fake_gerrit.addFakeChange('org/noop-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())
        self.assertEqual(len(self.history), 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_zuul_refs(self):
        "Test that zuul refs exist and have the right changes"
        self.worker.hold_jobs_in_build = True
        M1 = self.fake_gerrit.addFakeChange('org/project1', 'master', 'M1')
        M1.setMerged()
        M2 = self.fake_gerrit.addFakeChange('org/project2', 'master', 'M2')
        M2.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        a_zref = b_zref = c_zref = d_zref = None
        for x in self.builds:
            if x.parameters['ZUUL_CHANGE'] == '3':
                a_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '4':
                b_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '5':
                c_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '6':
                d_zref = x.parameters['ZUUL_REF']

        # There are... four... refs.
        self.assertIsNotNone(a_zref)
        self.assertIsNotNone(b_zref)
        self.assertIsNotNone(c_zref)
        self.assertIsNotNone(d_zref)

        # And they should all be different
        refs = set([a_zref, b_zref, c_zref, d_zref])
        self.assertEqual(len(refs), 4)

        # a ref should have a, not b, and should not be in project2
        self.assertTrue(self.ref_has_change(a_zref, A))
        self.assertFalse(self.ref_has_change(a_zref, B))
        self.assertFalse(self.ref_has_change(a_zref, M2))

        # b ref should have a and b, and should not be in project2
        self.assertTrue(self.ref_has_change(b_zref, A))
        self.assertTrue(self.ref_has_change(b_zref, B))
        self.assertFalse(self.ref_has_change(b_zref, M2))

        # c ref should have a and b in 1, c in 2
        self.assertTrue(self.ref_has_change(c_zref, A))
        self.assertTrue(self.ref_has_change(c_zref, B))
        self.assertTrue(self.ref_has_change(c_zref, C))
        self.assertFalse(self.ref_has_change(c_zref, D))

        # d ref should have a and b in 1, c and d in 2
        self.assertTrue(self.ref_has_change(d_zref, A))
        self.assertTrue(self.ref_has_change(d_zref, B))
        self.assertTrue(self.ref_has_change(d_zref, C))
        self.assertTrue(self.ref_has_change(d_zref, D))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
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
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.builds[0].run_error = True
        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(self.countJobResults(self.history, 'RUN_ERROR'), 1)
        self.assertEqual(self.countJobResults(self.history, 'SUCCESS'), 3)

    def test_statsd(self):
        "Test each of the statsd methods used in the scheduler"
        import extras
        statsd = extras.try_import('statsd.statsd')
        statsd.incr('test-incr')
        statsd.timing('test-timing', 3)
        statsd.gauge('test-gauge', 12)
        self.assertReportedStat('test-incr', '1|c')
        self.assertReportedStat('test-timing', '3|ms')
        self.assertReportedStat('test-gauge', '12|g')

    def test_stuck_job_cleanup(self):
        "Test that pending jobs are cleaned up if removed from layout"
        # This job won't be registered at startup because it is not in
        # the standard layout, but we need it to already be registerd
        # for when we reconfigure, as that is when Zuul will attempt
        # to run the new job.
        self.worker.registerFunction('build:gate-noop')
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.gearman_server.getQueue()), 1)

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-jobs.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.gearman_server.release('gate-noop')
        self.waitUntilSettled()
        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())

        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'gate-noop')
        self.assertEqual(self.history[0].result, 'SUCCESS')

    def test_file_jobs(self):
        "Test that file jobs run only when appropriate"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset(['pip-requires'])
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        testfile_jobs = [x for x in self.history
                         if x.name == 'project-testfile']

        self.assertEqual(len(testfile_jobs), 1)
        self.assertEqual(testfile_jobs[0].changes, '1,2')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def _test_skip_if_jobs(self, branch, should_skip):
        "Test that jobs with a skip-if filter run only when appropriate"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-skip-if.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        change = self.fake_gerrit.addFakeChange('org/project',
                                                branch,
                                                'test skip-if')
        self.fake_gerrit.addEvent(change.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        tested_change_ids = [x.changes[0] for x in self.history
                             if x.name == 'project-test-skip-if']

        if should_skip:
            self.assertEqual([], tested_change_ids)
        else:
            self.assertIn(change.data['number'], tested_change_ids)

    def test_skip_if_match_skips_job(self):
        self._test_skip_if_jobs(branch='master', should_skip=True)

    def test_skip_if_no_match_runs_job(self):
        self._test_skip_if_jobs(branch='mp', should_skip=False)

    def test_test_config(self):
        "Test that we can test the config"
        sched = zuul.scheduler.Scheduler()
        sched.registerTrigger(None, 'gerrit')
        sched.registerTrigger(None, 'timer')
        sched.registerTrigger(None, 'zuul')
        sched.testConfig(self.config.get('zuul', 'layout_config'))

    def test_build_description(self):
        "Test that build descriptions update"
        self.worker.registerFunction('set_description:' +
                                     self.worker.worker_id)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        desc = self.history[0].description
        self.log.debug("Description: %s" % desc)
        self.assertTrue(re.search("Branch.*master", desc))
        self.assertTrue(re.search("Pipeline.*gate", desc))
        self.assertTrue(re.search("project-merge.*SUCCESS", desc))
        self.assertTrue(re.search("project-test1.*SUCCESS", desc))
        self.assertTrue(re.search("project-test2.*SUCCESS", desc))
        self.assertTrue(re.search("Reported result.*SUCCESS", desc))

    def test_queue_names(self):
        "Test shared change queue names"
        project1 = self.sched.layout.projects['org/project1']
        project2 = self.sched.layout.projects['org/project2']
        q1 = self.sched.layout.pipelines['gate'].getQueue(project1)
        q2 = self.sched.layout.pipelines['gate'].getQueue(project2)
        self.assertEqual(q1.name, 'integration')
        self.assertEqual(q2.name, 'integration')

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-bad-queue.yaml')
        with testtools.ExpectedException(
            Exception, "More than one name assigned to change queue"):
            self.sched.reconfigure(self.config)

    def test_queue_precedence(self):
        "Test that queue precedence works"

        self.gearman_server.hold_jobs_in_queue = True
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        # Run one build at a time to ensure non-race order:
        for x in range(6):
            self.release(self.builds[0])
            self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.waitUntilSettled()

        self.log.debug(self.history)
        self.assertEqual(self.history[0].pipeline, 'gate')
        self.assertEqual(self.history[1].pipeline, 'check')
        self.assertEqual(self.history[2].pipeline, 'gate')
        self.assertEqual(self.history[3].pipeline, 'gate')
        self.assertEqual(self.history[4].pipeline, 'check')
        self.assertEqual(self.history[5].pipeline, 'check')

    def test_json_status(self):
        "Test that we can retrieve JSON status info"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        port = self.webapp.server.socket.getsockname()[1]

        req = urllib2.Request("http://localhost:%s/status.json" % port)
        f = urllib2.urlopen(req)
        headers = f.info()
        self.assertIn('Content-Length', headers)
        self.assertIn('Content-Type', headers)
        self.assertEqual(headers['Content-Type'],
                         'application/json; charset=UTF-8')
        self.assertIn('Last-Modified', headers)
        data = f.read()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        data = json.loads(data)
        status_jobs = set()
        for p in data['pipelines']:
            for q in p['change_queues']:
                if p['name'] in ['gate', 'conflict']:
                    self.assertEqual(q['window'], 20)
                else:
                    self.assertEqual(q['window'], 0)
                for head in q['heads']:
                    for change in head:
                        self.assertTrue(change['active'])
                        self.assertEqual(change['id'], '1,1')
                        for job in change['jobs']:
                            status_jobs.add(job['name'])
        self.assertIn('project-merge', status_jobs)
        self.assertIn('project-test1', status_jobs)
        self.assertIn('project-test2', status_jobs)

    def test_merging_queues(self):
        "Test that transitively-connected change queues are merged"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-queues.yaml')
        self.sched.reconfigure(self.config)
        self.assertEqual(len(self.sched.layout.pipelines['gate'].queues), 1)

    def test_node_label(self):
        "Test that a job runs on a specific node label"
        self.worker.registerFunction('build:node-project-test1:debian')

        A = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'debian')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

    def test_live_reconfiguration(self):
        "Test that live reconfiguration works"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_live_reconfiguration_functions(self):
        "Test live reconfiguration with a custom function"
        self.worker.registerFunction('build:node-project-test1:debian')
        self.worker.registerFunction('build:node-project-test1:wheezy')
        A = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'debian')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-live-'
                        'reconfiguration-functions.yaml')
        self.sched.reconfigure(self.config)
        self.worker.build_history = []

        B = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'B')
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'wheezy')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

    def test_delayed_repo_init(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-delayed-repo-init.yaml')
        self.sched.reconfigure(self.config)

        self.init_repo("org/new-project")
        A = self.fake_gerrit.addFakeChange('org/new-project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_repo_deleted(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-repo-deleted.yaml')
        self.sched.reconfigure(self.config)

        self.init_repo("org/delete-project")
        A = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
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
        shutil.rmtree(os.path.join(self.git_root, "org/delete-project"))

        B = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'B')

        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_timer(self):
        "Test that a periodic job is triggered"
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

        port = self.webapp.server.socket.getsockname()[1]

        f = urllib.urlopen("http://localhost:%s/status.json" % port)
        data = f.read()

        self.worker.hold_jobs_in_build = False
        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-old').result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-older').result, 'SUCCESS')

        data = json.loads(data)
        status_jobs = set()
        for p in data['pipelines']:
            for q in p['change_queues']:
                for head in q['heads']:
                    for change in head:
                        self.assertEqual(change['id'], None)
                        for job in change['jobs']:
                            status_jobs.add(job['name'])
        self.assertIn('project-bitrot-stable-old', status_jobs)
        self.assertIn('project-bitrot-stable-older', status_jobs)

    def test_idle(self):
        "Test that frequent periodic jobs work"
        self.worker.hold_jobs_in_build = True

        for x in range(1, 3):
            # Test that timer triggers periodic jobs even across
            # layout config reloads.
            # Start timer trigger
            self.config.set('zuul', 'layout_config',
                            'tests/fixtures/layout-idle.yaml')
            self.sched.reconfigure(self.config)
            self.registerJobs()

            # The pipeline triggers every second, so we should have seen
            # several by now.
            time.sleep(5)
            self.waitUntilSettled()

            # Stop queuing timer triggered jobs so that the assertions
            # below don't race against more jobs being queued.
            self.config.set('zuul', 'layout_config',
                            'tests/fixtures/layout-no-timer.yaml')
            self.sched.reconfigure(self.config)
            self.registerJobs()

            self.assertEqual(len(self.builds), 2)
            self.worker.release('.*')
            self.waitUntilSettled()
            self.assertEqual(len(self.builds), 0)
            self.assertEqual(len(self.history), x * 2)

    def test_check_smtp_pool(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-smtp.yaml')
        self.sched.reconfigure(self.config)

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

    def test_timer_smtp(self):
        "Test that a periodic job is triggered"
        self.worker.hold_jobs_in_build = True
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-timer-smtp.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 2)
        self.worker.release('.*')
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
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()
        self.waitUntilSettled()
        self.worker.release('.*')
        self.waitUntilSettled()

    def test_client_enqueue(self):
        "Test that the RPC client can enqueue a change"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        A.addApproval('APRV', 1)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.enqueue(pipeline='gate',
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

    def test_client_enqueue_negative(self):
        "Test that the RPC client returns errors"
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid project"):
            r = client.enqueue(pipeline='gate',
                               project='project-does-not-exist',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid pipeline"):
            r = client.enqueue(pipeline='pipeline-does-not-exist',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid trigger"):
            r = client.enqueue(pipeline='gate',
                               project='org/project',
                               trigger='trigger-does-not-exist',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid change"):
            r = client.enqueue(pipeline='gate',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)
        self.assertEqual(len(self.builds), 0)

    def test_client_promote(self):
        "Test that the RPC client can promote a change"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        items = self.sched.layout.pipelines['gate'].getAllItems()
        enqueue_times = {}
        for item in items:
            enqueue_times[str(item.change)] = item.enqueue_time

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.promote(pipeline='gate',
                           change_ids=['2,1', '3,1'])

        # ensure that enqueue times are durable
        items = self.sched.layout.pipelines['gate'].getAllItems()
        for item in items:
            self.assertEqual(
                enqueue_times[str(item.change)], item.enqueue_time)

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], B))
        self.assertFalse(self.job_has_changes(self.builds[0], A))
        self.assertFalse(self.job_has_changes(self.builds[0], C))

        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))
        self.assertFalse(self.job_has_changes(self.builds[2], A))

        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))
        self.assertTrue(self.job_has_changes(self.builds[4], A))

        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        client.shutdown()
        self.assertEqual(r, True)

    def test_client_promote_dependent(self):
        "Test that the RPC client can promote a dependent change"
        # C (depends on B) -> B -> A ; then promote C to get:
        # A -> C (depends on B) -> B
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.promote(pipeline='gate',
                           change_ids=['3,1'])

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], B))
        self.assertFalse(self.job_has_changes(self.builds[0], A))
        self.assertFalse(self.job_has_changes(self.builds[0], C))

        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))
        self.assertFalse(self.job_has_changes(self.builds[2], A))

        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))
        self.assertTrue(self.job_has_changes(self.builds[4], A))

        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        client.shutdown()
        self.assertEqual(r, True)

    def test_client_promote_negative(self):
        "Test that the RPC client returns errors for promotion"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(pipeline='nonexistent',
                               change_ids=['2,1', '3,1'])
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(pipeline='gate',
                               change_ids=['4,1'])
            client.shutdown()
            self.assertEqual(r, False)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_queue_rate_limiting(self):
        "Test that DependentPipelines are rate limited with dep across window"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-rate-limit.yaml')
        self.sched.reconfigure(self.config)
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)
        self.worker.addFailTest('project-test1', A)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        queue = self.sched.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')

        # Gate is reset and only B's merge job is queued because
        # window shrunk to 1.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only B's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # B was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(B.data['status'], 'MERGED')

        # Only C is left and its merge job is queued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # After successful merge job the test jobs for C are queued.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # C successfully merged so window is bumped to 3.
        self.assertEqual(queue.window, 3)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    def test_queue_rate_limiting_dependent(self):
        "Test that DependentPipelines are rate limited with dep in window"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-rate-limit.yaml')
        self.sched.reconfigure(self.config)
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        B.setDependsOn(A, 1)

        self.worker.addFailTest('project-test1', A)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        queue = self.sched.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        # Gate is reset and only C's merge job is queued because
        # window shrunk to 1 and A and B were dequeued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only C's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # C was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    def test_worker_update_metadata(self):
        "Test if a worker can send back metadata about itself"
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.launcher.builds), 1)

        self.log.debug('Current builds:')
        self.log.debug(self.launcher.builds)

        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = self.launcher.builds.values()[0]
            if build.worker.name == "My Worker":
                break
            else:
                time.sleep(0)

        self.log.debug(build)
        self.assertEqual("My Worker", build.worker.name)
        self.assertEqual("localhost", build.worker.hostname)
        self.assertEqual(['127.0.0.1', '192.168.1.1'], build.worker.ips)
        self.assertEqual("zuul.example.org", build.worker.fqdn)
        self.assertEqual("FakeBuilder", build.worker.program)
        self.assertEqual("v1.1", build.worker.version)
        self.assertEqual({'something': 'else'}, build.worker.extra)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_footer_message(self):
        "Test a pipeline's footer message is correctly added to the report."
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-footer-message.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('test1', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(2, len(self.smtp_messages))

        failure_body = """\
Build failed.  For information on how to proceed, see \
http://wiki.example.org/Test_Failures

- test1 http://logs.example.com/1/1/gate/test1/0 : FAILURE in 0s
- test2 http://logs.example.com/1/1/gate/test2/1 : SUCCESS in 0s

For CI problems and help debugging, contact ci@example.org"""

        success_body = """\
Build succeeded.

- test1 http://logs.example.com/2/1/gate/test1/2 : SUCCESS in 0s
- test2 http://logs.example.com/2/1/gate/test2/3 : SUCCESS in 0s

For CI problems and help debugging, contact ci@example.org"""

        self.assertEqual(failure_body, self.smtp_messages[0]['body'])
        self.assertEqual(success_body, self.smtp_messages[1]['body'])

    def test_merge_failure_reporters(self):
        """Check that the config is set up correctly"""

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-failure.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        self.assertEqual(
            "Merge Failed.\n\nThis change was unable to be automatically "
            "merged with the current state of the repository. Please rebase "
            "your change and upload a new patchset.",
            self.sched.layout.pipelines['check'].merge_failure_message)
        self.assertEqual(
            "The merge failed! For more information...",
            self.sched.layout.pipelines['gate'].merge_failure_message)

        self.assertEqual(
            len(self.sched.layout.pipelines['check'].merge_failure_actions), 1)
        self.assertEqual(
            len(self.sched.layout.pipelines['gate'].merge_failure_actions), 2)

        self.assertTrue(isinstance(
            self.sched.layout.pipelines['check'].merge_failure_actions[0].
            reporter, zuul.reporter.gerrit.Reporter))

        self.assertTrue(
            (
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[0].reporter,
                           zuul.reporter.smtp.Reporter) and
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[1].reporter,
                           zuul.reporter.gerrit.Reporter)
            ) or (
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[0].reporter,
                           zuul.reporter.gerrit.Reporter) and
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[1].reporter,
                           zuul.reporter.smtp.Reporter)
            )
        )

    def test_merge_failure_reports(self):
        """Check that when a change fails to merge the correct message is sent
        to the correct reporter"""
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-failure.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # Check a test failure isn't reported to SMTP
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('project-test1', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(3, len(self.history))  # 3 jobs
        self.assertEqual(0, len(self.smtp_messages))

        # Check a merge failure is reported to SMTP
        # B should be merged, but C will conflict with B
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset(['conflict'])
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.addPatchset(['conflict'])
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(6, len(self.history))  # A and B jobs
        self.assertEqual(1, len(self.smtp_messages))
        self.assertEqual('The merge failed! For more information...',
                         self.smtp_messages[0]['body'])

    def test_swift_instructions(self):
        "Test that the correct swift instructions are sent to the workers"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-swift.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/merge_logs/1/1/1/"
            "gate/test-merge/",
            self.builds[0].parameters['SWIFT_logs_URL'][:-7])
        self.assertEqual(5,
                         len(self.builds[0].parameters['SWIFT_logs_HMAC_BODY'].
                             split('\n')))
        self.assertIn('SWIFT_logs_SIGNATURE', self.builds[0].parameters)

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/logs/1/1/1/"
            "gate/test-test/",
            self.builds[1].parameters['SWIFT_logs_URL'][:-7])
        self.assertEqual(5,
                         len(self.builds[1].parameters['SWIFT_logs_HMAC_BODY'].
                             split('\n')))
        self.assertIn('SWIFT_logs_SIGNATURE', self.builds[1].parameters)

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/stash/1/1/1/"
            "gate/test-test/",
            self.builds[1].parameters['SWIFT_MOSTLY_URL'][:-7])
        self.assertEqual(5,
                         len(self.builds[1].
                             parameters['SWIFT_MOSTLY_HMAC_BODY'].split('\n')))
        self.assertIn('SWIFT_MOSTLY_SIGNATURE', self.builds[1].parameters)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_client_get_running_jobs(self):
        "Test that the RPC client can get a list of running jobs"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)

        # Wait for gearman server to send the initial workData back to zuul
        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = self.launcher.builds.values()[0]
            if build.worker.name == "My Worker":
                break
            else:
                time.sleep(0)

        running_items = client.get_running_jobs()

        self.assertEqual(1, len(running_items))
        running_item = running_items[0]
        self.assertEqual([], running_item['failing_reasons'])
        self.assertEqual([], running_item['items_behind'])
        self.assertEqual('https://hostname/1', running_item['url'])
        self.assertEqual(None, running_item['item_ahead'])
        self.assertEqual('org/project', running_item['project'])
        self.assertEqual(None, running_item['remaining_time'])
        self.assertEqual(True, running_item['active'])
        self.assertEqual('1,1', running_item['id'])

        self.assertEqual(3, len(running_item['jobs']))
        for job in running_item['jobs']:
            if job['name'] == 'project-merge':
                self.assertEqual('project-merge', job['name'])
                self.assertEqual('gate', job['pipeline'])
                self.assertEqual(False, job['retry'])
                self.assertEqual('https://server/job/project-merge/0/',
                                 job['url'])
                self.assertEqual(7, len(job['worker']))
                self.assertEqual(False, job['canceled'])
                self.assertEqual(True, job['voting'])
                self.assertEqual(None, job['result'])
                self.assertEqual('gate', job['pipeline'])
                break

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        running_items = client.get_running_jobs()
        self.assertEqual(0, len(running_items))

    def test_nonvoting_pipeline(self):
        "Test that a nonvoting pipeline (experimental) can still report"

        A = self.fake_gerrit.addFakeChange('org/experimental-project',
                                           'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(
            self.getJobFromHistory('experimental-project-test').result,
            'SUCCESS')
        self.assertEqual(A.reported, 1)

    def test_crd_gate(self):
        "Test cross-repo dependencies"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        AM2 = self.fake_gerrit.addFakeChange('org/project1', 'master', 'AM2')
        AM1 = self.fake_gerrit.addFakeChange('org/project1', 'master', 'AM1')
        AM2.setMerged()
        AM1.setMerged()

        BM2 = self.fake_gerrit.addFakeChange('org/project2', 'master', 'BM2')
        BM1 = self.fake_gerrit.addFakeChange('org/project2', 'master', 'BM1')
        BM2.setMerged()
        BM1.setMerged()

        # A -> AM1 -> AM2
        # B -> BM1 -> BM2
        # A Depends-On: B
        # M2 is here to make sure it is never queried.  If it is, it
        # means zuul is walking down the entire history of merged
        # changes.

        B.setDependsOn(BM1, 1)
        BM1.setDependsOn(BM2, 1)

        A.setDependsOn(AM1, 1)
        AM1.setDependsOn(AM2, 1)

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        source = self.sched.layout.pipelines['gate'].source
        source.maintainCache([])

        self.worker.hold_jobs_in_build = True
        B.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(AM2.queried, 0)
        self.assertEqual(BM2.queried, 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

        self.assertEqual(self.getJobFromHistory('project1-merge').changes,
                         '2,1 1,1')

    def test_crd_branch(self):
        "Test cross-repo dependencies in multiple branches"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'mp', 'C')
        C.data['id'] = B.data['id']
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        # A Depends-On: B+C
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.worker.hold_jobs_in_build = True
        B.addApproval('APRV', 1)
        C.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

        self.assertEqual(self.getJobFromHistory('project1-merge').changes,
                         '2,1 3,1 1,1')

    def test_crd_multiline(self):
        "Test multiple depends-on lines in commit"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        # A Depends-On: B+C
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\nDepends-On: %s\n' % (
            A.subject, B.data['id'], C.data['id'])

        self.worker.hold_jobs_in_build = True
        B.addApproval('APRV', 1)
        C.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

        self.assertEqual(self.getJobFromHistory('project1-merge').changes,
                         '2,1 3,1 1,1')

    def test_crd_unshared_gate(self):
        "Test cross-repo dependencies in unshared gate queues"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        # A and B do not share a queue, make sure that A is unable to
        # enqueue B (and therefore, A is unable to be enqueued).
        B.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 0)
        self.assertEqual(B.reported, 0)
        self.assertEqual(len(self.history), 0)

        # Enqueue and merge B alone.
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

        # Now that B is merged, A should be able to be enqueued and
        # merged.
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_crd_cycle(self):
        "Test cross-repo dependency cycles"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        # A -> B -> A (via commit-depends)

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 0)
        self.assertEqual(B.reported, 0)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

    def test_crd_check(self):
        "Test cross-repo dependencies in independent pipelines"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        queue = self.gearman_server.getQueue()
        ref = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project1")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1']
        self.assertEqual(repo_messages, correct_messages)

        path = os.path.join(self.git_root, "org/project2")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'B-1']
        self.assertEqual(repo_messages, correct_messages)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)

        self.assertEqual(self.history[0].changes, '2,1 1,1')
        self.assertEqual(len(self.sched.layout.pipelines['check'].queues), 0)

    def test_crd_check_git_depends(self):
        "Test single-repo dependencies in independent pipelines"
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')

        # Add two git-dependent changes and make sure they both report
        # success.
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)

        self.assertEqual(self.history[0].changes, '1,1')
        self.assertEqual(self.history[-1].changes, '1,1 2,1')
        self.assertEqual(len(self.sched.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.messages[0])
        self.assertIn('Build succeeded', B.messages[0])

    def test_crd_check_duplicate(self):
        "Test duplicate check in independent pipelines"
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        check_pipeline = self.sched.layout.pipelines['check']

        # Add two git-dependent changes...
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...make sure the live one is not duplicated...
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...but the non-live one is able to be.
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 3)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)

        self.assertEqual(self.history[0].changes, '1,1 2,1')
        self.assertEqual(self.history[1].changes, '1,1')
        self.assertEqual(len(self.sched.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.messages[0])
        self.assertIn('Build succeeded', B.messages[0])

    def test_crd_check_reconfiguration(self):
        "Test cross-repo dependencies re-enqueued in independent pipelines"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)

        # Make sure the items still share a change queue, and the
        # first one is not live.
        self.assertEqual(len(self.sched.layout.pipelines['check'].queues), 1)
        queue = self.sched.layout.pipelines['check'].queues[0]
        first_item = queue.queue[0]
        for item in queue.queue:
            self.assertEqual(item.queue, first_item.queue)
        self.assertFalse(first_item.live)
        self.assertTrue(queue.queue[1].live)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)

        self.assertEqual(self.history[0].changes, '2,1 1,1')
        self.assertEqual(len(self.sched.layout.pipelines['check'].queues), 0)

    def test_crd_check_ignore_dependencies(self):
        "Test cross-repo dependencies can be ignored"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-ignore-dependencies.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])
        # C git-depends on B
        C.setDependsOn(B, 1)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Make sure none of the items share a change queue, and all
        # are live.
        check_pipeline = self.sched.layout.pipelines['check']
        self.assertEqual(len(check_pipeline.queues), 3)
        self.assertEqual(len(check_pipeline.getAllItems()), 3)
        for item in check_pipeline.getAllItems():
            self.assertTrue(item.live)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 1)

        # Each job should have tested exactly one change
        for job in self.history:
            self.assertEqual(len(job.changes.split()), 1)
