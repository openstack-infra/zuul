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


class TestGithubCrossRepoDeps(ZuulTestCase):
    """Test Github cross-repo dependencies"""
    config_file = 'zuul-github-driver.conf'

    @simple_layout('layouts/crd-github.yaml', driver='github')
    def test_crd_independent(self):
        "Test cross-repo dependences on an independent pipeline"

        # Create a change in project1 that a project2 change will depend on
        A = self.fake_github.openFakePullRequest('org/project1', 'master', 'A')

        # Create a commit in B that sets the dependency on A
        msg = "Depends-On: https://github.com/org/project1/pull/%s" % A.number
        B = self.fake_github.openFakePullRequest('org/project2', 'master', 'B',
                                                 body=msg)

        # Make an event to re-use
        event = B.getPullRequestEditedEvent()

        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        # The changes for the job from project2 should include the project1
        # PR contet
        changes = self.getJobFromHistory(
            'project2-test', 'org/project2').changes

        self.assertEqual(changes, "%s,%s %s,%s" % (A.number,
                                                   A.head_sha,
                                                   B.number,
                                                   B.head_sha))

        # There should be no more changes in the queue
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    @simple_layout('layouts/crd-github.yaml', driver='github')
    def test_crd_dependent(self):
        "Test cross-repo dependences on a dependent pipeline"

        # Create a change in project3 that a project4 change will depend on
        A = self.fake_github.openFakePullRequest('org/project3', 'master', 'A')

        # Create a commit in B that sets the dependency on A
        msg = "Depends-On: https://github.com/org/project3/pull/%s" % A.number
        B = self.fake_github.openFakePullRequest('org/project4', 'master', 'B',
                                                 body=msg)

        # Make an event to re-use
        event = B.getPullRequestEditedEvent()

        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        # The changes for the job from project4 should include the project3
        # PR contet
        changes = self.getJobFromHistory(
            'project4-test', 'org/project4').changes

        self.assertEqual(changes, "%s,%s %s,%s" % (A.number,
                                                   A.head_sha,
                                                   B.number,
                                                   B.head_sha))

        self.assertTrue(A.is_merged)
        self.assertTrue(B.is_merged)

    @simple_layout('layouts/crd-github.yaml', driver='github')
    def test_crd_unshared_dependent(self):
        "Test cross-repo dependences on unshared dependent pipeline"

        # Create a change in project1 that a project2 change will depend on
        A = self.fake_github.openFakePullRequest('org/project5', 'master', 'A')

        # Create a commit in B that sets the dependency on A
        msg = "Depends-On: https://github.com/org/project5/pull/%s" % A.number
        B = self.fake_github.openFakePullRequest('org/project6', 'master', 'B',
                                                 body=msg)

        # Make an event for B
        event = B.getPullRequestEditedEvent()

        # Emit for B, which should not enqueue A because they do not share
        # A queue. Since B depends on A, and A isn't enqueue, B will not run
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        self.assertEqual(0, len(self.history))

        # Enqueue A alone, let it finish
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        self.assertTrue(A.is_merged)
        self.assertFalse(B.is_merged)
        self.assertEqual(1, len(self.history))

        # With A merged, B should go through
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        self.assertTrue(B.is_merged)
        self.assertEqual(2, len(self.history))

    @simple_layout('layouts/crd-github.yaml', driver='github')
    def test_crd_cycle(self):
        "Test cross-repo dependency cycles"

        # A -> B -> A
        msg = "Depends-On: https://github.com/org/project6/pull/2"
        A = self.fake_github.openFakePullRequest('org/project5', 'master', 'A',
                                                 body=msg)
        msg = "Depends-On: https://github.com/org/project5/pull/1"
        B = self.fake_github.openFakePullRequest('org/project6', 'master', 'B',
                                                 body=msg)

        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertFalse(B.is_merged)
        self.assertEqual(0, len(self.history))

    @simple_layout('layouts/crd-github.yaml', driver='github')
    def test_crd_needed_changes(self):
        "Test cross-repo needed changes discovery"

        # Given change A and B, where B depends on A, when A
        # completes B should be enqueued (using a shared queue)

        # Create a change in project3 that a project4 change will depend on
        A = self.fake_github.openFakePullRequest('org/project3', 'master', 'A')

        # Set B to depend on A
        msg = "Depends-On: https://github.com/org/project3/pull/%s" % A.number
        B = self.fake_github.openFakePullRequest('org/project4', 'master', 'B',
                                                 body=msg)

        # Enqueue A, which when finished should enqueue B
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        # The changes for the job from project4 should include the project3
        # PR contet
        changes = self.getJobFromHistory(
            'project4-test', 'org/project4').changes

        self.assertEqual(changes, "%s,%s %s,%s" % (A.number,
                                                   A.head_sha,
                                                   B.number,
                                                   B.head_sha))

        self.assertTrue(A.is_merged)
        self.assertTrue(B.is_merged)
