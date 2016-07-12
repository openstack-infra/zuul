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

from zuul import change_matcher as cm
from zuul import model

from tests.base import BaseTestCase


class TestJob(BaseTestCase):

    @property
    def job(self):
        job = model.Job('job')
        job.skip_if_matcher = cm.MatchAll([
            cm.ProjectMatcher('^project$'),
            cm.MatchAllFiles([cm.FileMatcher('^docs/.*$')]),
        ])
        return job

    def test_change_matches_returns_false_for_matched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'docs/foo']
        self.assertFalse(self.job.changeMatches(change))

    def test_change_matches_returns_true_for_unmatched_skip_if(self):
        change = model.Change('project')
        change.files = ['/COMMIT_MSG', 'foo']
        self.assertTrue(self.job.changeMatches(change))

    def test_copy_retains_skip_if(self):
        job = model.Job('job')
        job.copy(self.job)
        self.assertTrue(job.skip_if_matcher)

    def _assert_job_booleans_are_not_none(self, job):
        self.assertIsNotNone(job.voting)
        self.assertIsNotNone(job.hold_following_changes)

    def test_job_sets_defaults_for_boolean_attributes(self):
        job = model.Job('job')
        self._assert_job_booleans_are_not_none(job)

    def test_metajob_does_not_set_defaults_for_boolean_attributes(self):
        job = model.Job('^job')
        self.assertIsNone(job.voting)
        self.assertIsNone(job.hold_following_changes)

    def test_metajob_copy_does_not_set_undefined_boolean_attributes(self):
        job = model.Job('job')
        metajob = model.Job('^job')
        job.copy(metajob)
        self._assert_job_booleans_are_not_none(job)


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
