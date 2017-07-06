#!/usr/bin/env python
# Copyright (c) 2017 IBM Corp.
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

import time

from tests.base import ZuulTestCase, simple_layout


class TestGithubRequirements(ZuulTestCase):
    """Test pipeline and trigger requirements"""
    config_file = 'zuul-github-driver.conf'

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_status(self):
        "Test pipeline requirement: status"
        project = 'org/project1'
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No status from zuul so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # An error status should not cause it to be enqueued
        self.fake_github.setCommitStatus(project, A.head_sha, 'error',
                                         context='check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status goes in
        self.fake_github.setCommitStatus(project, A.head_sha, 'success',
                                         context='check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project1-pipeline')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_trigger_require_status(self):
        "Test trigger requirement: status"
        project = 'org/project1'
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('trigger me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No status from zuul so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # An error status should not cause it to be enqueued
        self.fake_github.setCommitStatus(project, A.head_sha, 'error',
                                         context='check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status goes in
        self.fake_github.setCommitStatus(project, A.head_sha, 'success',
                                         context='check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project1-pipeline')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_trigger_on_status(self):
        "Test trigger on: status"
        project = 'org/project2'
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')

        # An error status should not cause it to be enqueued
        self.fake_github.setCommitStatus(project, A.head_sha, 'error',
                                         context='check')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check',
                                                          state='error'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status from unknown user should not cause it to be
        # enqueued
        self.fake_github.setCommitStatus(project, A.head_sha, 'success',
                                         context='check', user='foo')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check',
                                                          state='success',
                                                          user='foo'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status from zuul goes in
        self.fake_github.setCommitStatus(project, A.head_sha, 'success',
                                         context='check')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project2-trigger')

        # An error status for a different context should not cause it to be
        # enqueued
        self.fake_github.setCommitStatus(project, A.head_sha, 'error',
                                         context='gate')
        self.fake_github.emitEvent(A.getCommitStatusEvent('gate',
                                                          state='error'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_review_username(self):
        "Test pipeline requirement: review username"

        A = self.fake_github.openFakePullRequest('org/project3', 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No approval from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an approved review from derp
        A.addReview('derp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project3-reviewusername')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_review_state(self):
        "Test pipeline requirement: review state"

        A = self.fake_github.openFakePullRequest('org/project4', 'master', 'A')
        # Add derp to writers
        A.writers.extend(('derp', 'werp'))
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A negative review from derp should not cause it to be enqueued
        A.addReview('derp', 'CHANGES_REQUESTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A negative review from werp should not cause it to be enqueued
        A.addReview('werp', 'CHANGES_REQUESTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive from nobody should not cause it to be enqueued
        A.addReview('nobody', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review from derp should still be blocked by the
        # negative review from werp
        A.addReview('derp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review from werp should cause it to be enqueued
        A.addReview('werp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project4-reviewreq')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_review_user_state(self):
        "Test pipeline requirement: review state from user"

        A = self.fake_github.openFakePullRequest('org/project5', 'master', 'A')
        # Add derp and herp to writers
        A.writers.extend(('derp', 'herp'))
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A negative review from derp should not cause it to be enqueued
        A.addReview('derp', 'CHANGES_REQUESTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive from nobody should not cause it to be enqueued
        A.addReview('nobody', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review from herp (a writer) should not cause it to be
        # enqueued
        A.addReview('herp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review from derp should cause it to be enqueued
        A.addReview('derp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project5-reviewuserstate')

# TODO: Implement reject on approval username/state

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_review_latest_user_state(self):
        "Test pipeline requirement: review state from user"

        A = self.fake_github.openFakePullRequest('org/project5', 'master', 'A')
        # Add derp and herp to writers
        A.writers.extend(('derp', 'herp'))
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # The first negative review from derp should not cause it to be
        # enqueued
        A.addReview('derp', 'CHANGES_REQUESTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review from derp should cause it to be enqueued
        A.addReview('derp', 'APPROVED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project5-reviewuserstate')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_review_comment_masked(self):
        "Test pipeline requirement: review comments on top of votes"

        A = self.fake_github.openFakePullRequest('org/project5', 'master', 'A')
        # Add derp to writers
        A.writers.append('derp')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # The first negative review from derp should not cause it to be
        # enqueued
        A.addReview('derp', 'CHANGES_REQUESTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A positive review is required, so provide it
        A.addReview('derp', 'APPROVED')

        # Add a comment review on top to make sure we can still enqueue
        A.addReview('derp', 'COMMENTED')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project5-reviewuserstate')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_require_review_newer_than(self):

        A = self.fake_github.openFakePullRequest('org/project6', 'master', 'A')
        # Add derp and herp to writers
        A.writers.extend(('derp', 'herp'))
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a too-old positive review, should not be enqueued
        submitted_at = time.time() - 72 * 60 * 60
        A.addReview('derp', 'APPROVED',
                    submitted_at)
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add a recent positive review
        submitted_at = time.time() - 12 * 60 * 60
        A.addReview('derp', 'APPROVED', submitted_at)
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project6-newerthan')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_require_review_older_than(self):

        A = self.fake_github.openFakePullRequest('org/project7', 'master', 'A')
        # Add derp and herp to writers
        A.writers.extend(('derp', 'herp'))
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No positive review from derp so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a too-new positive, should not be enqueued
        submitted_at = time.time() - 12 * 60 * 60
        A.addReview('derp', 'APPROVED',
                    submitted_at)
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add an old enough positive, should enqueue
        submitted_at = time.time() - 72 * 60 * 60
        A.addReview('herp', 'APPROVED', submitted_at)
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project7-olderthan')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_require_open(self):

        A = self.fake_github.openFakePullRequest('org/project8', 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()

        # PR is open, we should have enqueued
        self.assertEqual(len(self.history), 1)

        # close the PR and try again
        A.state = 'closed'
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # PR is closed, should not trigger
        self.assertEqual(len(self.history), 1)

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_require_current(self):

        A = self.fake_github.openFakePullRequest('org/project9', 'master', 'A')
        # A sync event that we will keep submitting to trigger
        sync = A.getPullRequestSynchronizeEvent()
        self.fake_github.emitEvent(sync)
        self.waitUntilSettled()

        # PR head is current should enqueue
        self.assertEqual(len(self.history), 1)

        # Add a commit to the PR, re-issue the original comment event
        A.addCommit()
        self.fake_github.emitEvent(sync)
        self.waitUntilSettled()
        # Event hash is not current, should not trigger
        self.assertEqual(len(self.history), 1)

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_label(self):
        "Test pipeline requirement: label"
        A = self.fake_github.openFakePullRequest('org/project10', 'master',
                                                 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No label so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A derp label should not cause it to be enqueued
        A.addLabel('derp')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # An approved label goes in
        A.addLabel('approved')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project10-label')
