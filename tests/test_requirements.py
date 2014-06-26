#!/usr/bin/env python

# Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
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

import logging
import time

from tests.base import ZuulTestCase

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


class TestRequirements(ZuulTestCase):
    """Test pipeline and trigger requirements"""

    def test_pipeline_require_approval_newer_than(self):
        "Test pipeline requirement: approval newer than"
        return self._test_require_approval_newer_than('org/project1',
                                                      'project1-pipeline')

    def test_trigger_require_approval_newer_than(self):
        "Test trigger requirement: approval newer than"
        return self._test_require_approval_newer_than('org/project2',
                                                      'project2-trigger')

    def _test_require_approval_newer_than(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-newer-than.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a too-old +1, should not be enqueued
        A.addApproval('VRFY', 1, username='jenkins',
                      granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add a recent +1
        self.fake_gerrit.addEvent(A.addApproval('VRFY', 1, username='jenkins'))
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

    def test_pipeline_require_approval_older_than(self):
        "Test pipeline requirement: approval older than"
        return self._test_require_approval_older_than('org/project1',
                                                      'project1-pipeline')

    def test_trigger_require_approval_older_than(self):
        "Test trigger requirement: approval older than"
        return self._test_require_approval_older_than('org/project2',
                                                      'project2-trigger')

    def _test_require_approval_older_than(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-older-than.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a recent +1 which should not be enqueued
        A.addApproval('VRFY', 1)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add an old +1 which should be enqueued
        A.addApproval('VRFY', 1, username='jenkins',
                      granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

    def test_pipeline_require_approval_username(self):
        "Test pipeline requirement: approval username"
        return self._test_require_approval_username('org/project1',
                                                    'project1-pipeline')

    def test_trigger_require_approval_username(self):
        "Test trigger requirement: approval username"
        return self._test_require_approval_username('org/project2',
                                                    'project2-trigger')

    def _test_require_approval_username(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-username.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an approval from Jenkins
        A.addApproval('VRFY', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

    def test_pipeline_require_approval_email(self):
        "Test pipeline requirement: approval email"
        return self._test_require_approval_email('org/project1',
                                                 'project1-pipeline')

    def test_trigger_require_approval_email(self):
        "Test trigger requirement: approval email"
        return self._test_require_approval_email('org/project2',
                                                 'project2-trigger')

    def _test_require_approval_email(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-email.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an approval from Jenkins
        A.addApproval('VRFY', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

    def test_pipeline_require_approval_vote1(self):
        "Test pipeline requirement: approval vote with one value"
        return self._test_require_approval_vote1('org/project1',
                                                 'project1-pipeline')

    def test_trigger_require_approval_vote1(self):
        "Test trigger requirement: approval vote with one value"
        return self._test_require_approval_vote1('org/project2',
                                                 'project2-trigger')

    def _test_require_approval_vote1(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-vote1.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A -1 from jenkins should not cause it to be enqueued
        A.addApproval('VRFY', -1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A +1 should allow it to be enqueued
        A.addApproval('VRFY', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

    def test_pipeline_require_approval_vote2(self):
        "Test pipeline requirement: approval vote with two values"
        return self._test_require_approval_vote2('org/project1',
                                                 'project1-pipeline')

    def test_trigger_require_approval_vote2(self):
        "Test trigger requirement: approval vote with two values"
        return self._test_require_approval_vote2('org/project2',
                                                 'project2-trigger')

    def _test_require_approval_vote2(self, project, job):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-vote2.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A -1 from jenkins should not cause it to be enqueued
        A.addApproval('VRFY', -1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A -2 from jenkins should not cause it to be enqueued
        A.addApproval('VRFY', -2, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A +1 from jenkins should allow it to be enqueued
        A.addApproval('VRFY', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # A +2 should allow it to be enqueued
        B = self.fake_gerrit.addFakeChange(project, 'master', 'B')
        # A comment event that we will keep submitting to trigger
        comment = B.addApproval('CRVW', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        B.addApproval('VRFY', 2, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, job)

    def test_pipeline_require_current_patchset(self):
        "Test pipeline requirement: current-patchset"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-'
                        'current-patchset.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()
        # Create two patchsets and let their tests settle out. Then
        # comment on first patchset and check that no additional
        # jobs are run.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 1))
        self.waitUntilSettled()
        A.addPatchset()
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)  # one job for each ps
        self.fake_gerrit.addEvent(A.getChangeCommentEvent(1))
        self.waitUntilSettled()

        # Assert no new jobs ran after event for old patchset.
        self.assertEqual(len(self.history), 2)

        # Make sure the same event on a new PS will trigger
        self.fake_gerrit.addEvent(A.getChangeCommentEvent(2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 3)

    def test_pipeline_require_open(self):
        "Test pipeline requirement: open"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-open.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           status='MERGED')
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.fake_gerrit.addEvent(B.addApproval('CRVW', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    def test_pipeline_require_status(self):
        "Test pipeline requirement: status"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-requirement-status.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           status='MERGED')
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.fake_gerrit.addEvent(B.addApproval('CRVW', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    def _test_require_reject_username(self, project, job):
        "Test negative username's match"
        # Should only trigger if Jenkins hasn't voted.
        self.config.set(
            'zuul', 'layout_config',
            'tests/fixtures/layout-requirement-reject-username.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # add in a change with no comments
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # add in a comment that will trigger
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 1,
                                                username='reviewer'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # add in a comment from jenkins user which shouldn't trigger
        self.fake_gerrit.addEvent(A.addApproval('VRFY', 1, username='jenkins'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Check future reviews also won't trigger as a 'jenkins' user has
        # commented previously
        self.fake_gerrit.addEvent(A.addApproval('CRVW', 1,
                                                username='reviewer'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    def test_pipeline_reject_username(self):
        "Test negative pipeline requirement: no comment from jenkins"
        return self._test_require_reject_username('org/project1',
                                                  'project1-pipeline')

    def test_trigger_reject_username(self):
        "Test negative trigger requirement: no comment from jenkins"
        return self._test_require_reject_username('org/project2',
                                                  'project2-trigger')

    def _test_require_reject(self, project, job):
        "Test no approval matches a reject param"
        self.config.set(
            'zuul', 'layout_config',
            'tests/fixtures/layout-requirement-reject.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # First positive vote should not queue until jenkins has +1'd
        comment = A.addApproval('VRFY', 1, username='reviewer_a')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Jenkins should put in a +1 which will also queue
        comment = A.addApproval('VRFY', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # Negative vote should not queue
        comment = A.addApproval('VRFY', -1, username='reviewer_b')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Future approvals should do nothing
        comment = A.addApproval('VRFY', 1, username='reviewer_c')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Change/update negative vote should queue
        comment = A.addApproval('VRFY', 1, username='reviewer_b')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, job)

        # Future approvals should also queue
        comment = A.addApproval('VRFY', 1, username='reviewer_d')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 3)
        self.assertEqual(self.history[2].name, job)

    def test_pipeline_require_reject(self):
        "Test pipeline requirement: rejections absent"
        return self._test_require_reject('org/project1', 'project1-pipeline')

    def test_trigger_require_reject(self):
        "Test trigger requirement: rejections absent"
        return self._test_require_reject('org/project2', 'project2-trigger')
