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

import time

from tests.base import ZuulTestCase


class TestRequirementsApprovalNewerThan(ZuulTestCase):
    """Requirements with a newer-than comment requirement"""

    tenant_config_file = 'config/requirements/newer-than/main.yaml'

    def test_pipeline_require_approval_newer_than(self):
        "Test pipeline requirement: approval newer than"
        return self._test_require_approval_newer_than('org/project1',
                                                      'project1-job')

    def test_trigger_require_approval_newer_than(self):
        "Test trigger requirement: approval newer than"
        return self._test_require_approval_newer_than('org/project2',
                                                      'project2-job')

    def _test_require_approval_newer_than(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a too-old +1, should not be enqueued
        A.addApproval('Verified', 1, username='jenkins',
                      granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add a recent +1
        self.fake_gerrit.addEvent(A.addApproval('Verified', 1,
                                                username='jenkins'))
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)


class TestRequirementsApprovalOlderThan(ZuulTestCase):
    """Requirements with a older-than comment requirement"""

    tenant_config_file = 'config/requirements/older-than/main.yaml'

    def test_pipeline_require_approval_older_than(self):
        "Test pipeline requirement: approval older than"
        return self._test_require_approval_older_than('org/project1',
                                                      'project1-job')

    def test_trigger_require_approval_older_than(self):
        "Test trigger requirement: approval older than"
        return self._test_require_approval_older_than('org/project2',
                                                      'project2-job')

    def _test_require_approval_older_than(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a recent +1 which should not be enqueued
        A.addApproval('Verified', 1)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Add an old +1 which should be enqueued
        A.addApproval('Verified', 1, username='jenkins',
                      granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)


class TestRequirementsUserName(ZuulTestCase):
    """Requirements with a username requirement"""

    tenant_config_file = 'config/requirements/username/main.yaml'

    def test_pipeline_require_approval_username(self):
        "Test pipeline requirement: approval username"
        return self._test_require_approval_username('org/project1',
                                                    'project1-job')

    def test_trigger_require_approval_username(self):
        "Test trigger requirement: approval username"
        return self._test_require_approval_username('org/project2',
                                                    'project2-job')

    def _test_require_approval_username(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an approval from Jenkins
        A.addApproval('Verified', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)


class TestRequirementsEmail(ZuulTestCase):
    """Requirements with a email requirement"""

    tenant_config_file = 'config/requirements/email/main.yaml'

    def test_pipeline_require_approval_email(self):
        "Test pipeline requirement: approval email"
        return self._test_require_approval_email('org/project1',
                                                 'project1-job')

    def test_trigger_require_approval_email(self):
        "Test trigger requirement: approval email"
        return self._test_require_approval_email('org/project2',
                                                 'project2-job')

    def _test_require_approval_email(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an approval from Jenkins
        A.addApproval('Verified', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)


class TestRequirementsVote1(ZuulTestCase):
    """Requirements with a voting requirement"""

    tenant_config_file = 'config/requirements/vote1/main.yaml'

    def test_pipeline_require_approval_vote1(self):
        "Test pipeline requirement: approval vote with one value"
        return self._test_require_approval_vote1('org/project1',
                                                 'project1-job')

    def test_trigger_require_approval_vote1(self):
        "Test trigger requirement: approval vote with one value"
        return self._test_require_approval_vote1('org/project2',
                                                 'project2-job')

    def _test_require_approval_vote1(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A -1 from jenkins should not cause it to be enqueued
        A.addApproval('Verified', -1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A +1 should allow it to be enqueued
        A.addApproval('Verified', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)


class TestRequirementsVote2(ZuulTestCase):
    """Requirements with a voting requirement"""

    tenant_config_file = 'config/requirements/vote2/main.yaml'

    def test_pipeline_require_approval_vote2(self):
        "Test pipeline requirement: approval vote with two values"
        return self._test_require_approval_vote2('org/project1',
                                                 'project1-job')

    def test_trigger_require_approval_vote2(self):
        "Test trigger requirement: approval vote with two values"
        return self._test_require_approval_vote2('org/project2',
                                                 'project2-job')

    def _test_require_approval_vote2(self, project, job):
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        # A comment event that we will keep submitting to trigger
        comment = A.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        # No approval from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # A -1 from jenkins should not cause it to be enqueued
        A.addApproval('Verified', -1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A -2 from jenkins should not cause it to be enqueued
        A.addApproval('Verified', -2, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # A +1 from jenkins should allow it to be enqueued
        A.addApproval('Verified', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # A +2 from nobody should not cause it to be enqueued
        B = self.fake_gerrit.addFakeChange(project, 'master', 'B')
        # A comment event that we will keep submitting to trigger
        comment = B.addApproval('Code-Review', 2, username='nobody')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # A +2 from jenkins should allow it to be enqueued
        B.addApproval('Verified', 2, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, job)


class TestRequirementsState(ZuulTestCase):
    """Requirements with simple state requirement"""

    tenant_config_file = 'config/requirements/state/main.yaml'

    def test_pipeline_require_current_patchset(self):
        # Create two patchsets and let their tests settle out. Then
        # comment on first patchset and check that no additional
        # jobs are run.
        A = self.fake_gerrit.addFakeChange('current-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 1))
        self.waitUntilSettled()
        A.addPatchset()
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 1))
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
        A = self.fake_gerrit.addFakeChange('open-project', 'master', 'A',
                                           status='MERGED')
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        B = self.fake_gerrit.addFakeChange('open-project', 'master', 'B')
        self.fake_gerrit.addEvent(B.addApproval('Code-Review', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    def test_pipeline_require_status(self):
        A = self.fake_gerrit.addFakeChange('status-project', 'master', 'A',
                                           status='MERGED')
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        B = self.fake_gerrit.addFakeChange('status-project', 'master', 'B')
        self.fake_gerrit.addEvent(B.addApproval('Code-Review', 2))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)


class TestRequirementsRejectUsername(ZuulTestCase):
    """Requirements with reject username requirement"""

    tenant_config_file = 'config/requirements/reject-username/main.yaml'

    def _test_require_reject_username(self, project, job):
        "Test negative username's match"
        # Should only trigger if Jenkins hasn't voted.
        # add in a change with no comments
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # add in a comment that will trigger
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 1,
                                                username='reviewer'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # add in a comment from jenkins user which shouldn't trigger
        self.fake_gerrit.addEvent(A.addApproval('Verified', 1,
                                                username='jenkins'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Check future reviews also won't trigger as a 'jenkins' user has
        # commented previously
        self.fake_gerrit.addEvent(A.addApproval('Code-Review', 1,
                                                username='reviewer'))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

    def test_pipeline_reject_username(self):
        "Test negative pipeline requirement: no comment from jenkins"
        return self._test_require_reject_username('org/project1',
                                                  'project1-job')

    def test_trigger_reject_username(self):
        "Test negative trigger requirement: no comment from jenkins"
        return self._test_require_reject_username('org/project2',
                                                  'project2-job')


class TestRequirementsReject(ZuulTestCase):
    """Requirements with reject requirement"""

    tenant_config_file = 'config/requirements/reject/main.yaml'

    def _test_require_reject(self, project, job):
        "Test no approval matches a reject param"
        A = self.fake_gerrit.addFakeChange(project, 'master', 'A')
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # First positive vote should not queue until jenkins has +1'd
        comment = A.addApproval('Verified', 1, username='reviewer_a')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Jenkins should put in a +1 which will also queue
        comment = A.addApproval('Verified', 1, username='jenkins')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, job)

        # Negative vote should not queue
        comment = A.addApproval('Verified', -1, username='reviewer_b')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Future approvals should do nothing
        comment = A.addApproval('Verified', 1, username='reviewer_c')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # Change/update negative vote should queue
        comment = A.addApproval('Verified', 1, username='reviewer_b')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, job)

        # Future approvals should also queue
        comment = A.addApproval('Verified', 1, username='reviewer_d')
        self.fake_gerrit.addEvent(comment)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 3)
        self.assertEqual(self.history[2].name, job)

    def test_pipeline_require_reject(self):
        "Test pipeline requirement: rejections absent"
        return self._test_require_reject('org/project1', 'project1-job')

    def test_trigger_require_reject(self):
        "Test trigger requirement: rejections absent"
        return self._test_require_reject('org/project2', 'project2-job')
