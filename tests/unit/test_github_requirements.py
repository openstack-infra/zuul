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

from tests.base import ZuulTestCase, simple_layout


class TestGithubRequirements(ZuulTestCase):
    """Test pipeline and trigger requirements"""
    config_file = 'zuul-github-driver.conf'

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_pipeline_require_status(self):
        "Test pipeline requirement: status"
        A = self.fake_github.openFakePullRequest('org/project1', 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.getCommentAddedEvent('test me')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        # No status from zuul so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # An error status should not cause it to be enqueued
        A.setStatus(A.head_sha, 'error', 'null', 'null', 'check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status goes in
        A.setStatus(A.head_sha, 'success', 'null', 'null', 'check')
        self.fake_github.emitEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project1-pipeline')

    @simple_layout('layouts/requirements-github.yaml', driver='github')
    def test_trigger_require_status(self):
        "Test trigger requirement: status"
        A = self.fake_github.openFakePullRequest('org/project2', 'master', 'A')

        # An error status should not cause it to be enqueued
        A.setStatus(A.head_sha, 'error', 'null', 'null', 'check')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check',
                                                          state='error'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # An success status from unknown user should not cause it to be
        # enqueued
        A.setStatus(A.head_sha, 'success', 'null', 'null', 'check', user='foo')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check',
                                                          state='success',
                                                          user='foo'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A success status goes in
        A.setStatus(A.head_sha, 'success', 'null', 'null', 'check')
        self.fake_github.emitEvent(A.getCommitStatusEvent('check'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project2-trigger')

        # An error status for a different context should not cause it to be
        # enqueued
        A.setStatus(A.head_sha, 'error', 'null', 'null', 'gate')
        self.fake_github.emitEvent(A.getCommitStatusEvent('gate',
                                                          state='error'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
