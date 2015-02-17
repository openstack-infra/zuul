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
        change.files = ['docs/foo']
        self.assertFalse(self.job.changeMatches(change))

    def test_change_matches_returns_true_for_unmatched_skip_if(self):
        change = model.Change('project')
        change.files = ['foo']
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
