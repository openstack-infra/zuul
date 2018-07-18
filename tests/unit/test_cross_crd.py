# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2018 Red Hat, Inc.
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

from tests.base import (
    ZuulTestCase,
)


class TestGerritToGithubCRD(ZuulTestCase):
    config_file = 'zuul-gerrit-github.conf'
    tenant_config_file = 'config/cross-source/main.yaml'

    def test_crd_gate(self):
        "Test cross-repo dependencies"
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'B')

        A.addApproval('Code-Review', 2)

        AM2 = self.fake_gerrit.addFakeChange('gerrit/project1', 'master',
                                             'AM2')
        AM1 = self.fake_gerrit.addFakeChange('gerrit/project1', 'master',
                                             'AM1')
        AM2.setMerged()
        AM1.setMerged()

        # A -> AM1 -> AM2
        # A Depends-On: B
        # M2 is here to make sure it is never queried.  If it is, it
        # means zuul is walking down the entire history of merged
        # changes.

        A.setDependsOn(AM1, 1)
        AM1.setDependsOn(AM2, 1)

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)

        for connection in self.connections.connections.values():
            connection.maintainCache([])

        self.executor_server.hold_jobs_in_build = True
        B.addLabel('approved')
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(AM2.queried, 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertTrue(B.is_merged)
        self.assertEqual(A.reported, 2)
        self.assertEqual(len(B.comments), 2)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 1,1' % B.head_sha)

    def test_crd_branch(self):
        "Test cross-repo dependencies in multiple branches"

        self.create_branch('github/project2', 'mp')
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'B')
        C1 = self.fake_github.openFakePullRequest('github/project2', 'mp',
                                                  'C1')

        A.addApproval('Code-Review', 2)

        # A Depends-On: B+C1
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\nDepends-On: %s\n' % (
            A.subject, B.url, C1.url)

        self.executor_server.hold_jobs_in_build = True
        B.addLabel('approved')
        C1.addLabel('approved')
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertTrue(B.is_merged)
        self.assertTrue(C1.is_merged)
        self.assertEqual(A.reported, 2)
        self.assertEqual(len(B.comments), 2)
        self.assertEqual(len(C1.comments), 2)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 2,%s 1,1' %
                         (B.head_sha, C1.head_sha))

    def test_crd_gate_reverse(self):
        "Test reverse cross-repo dependencies"
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'B')
        A.addApproval('Code-Review', 2)

        # A Depends-On: B

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)

        self.executor_server.hold_jobs_in_build = True
        A.addApproval('Approved', 1)
        self.fake_github.emitEvent(B.addLabel('approved'))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertTrue(B.is_merged)
        self.assertEqual(A.reported, 2)
        self.assertEqual(len(B.comments), 2)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 1,1' %
                         (B.head_sha,))

    def test_crd_cycle(self):
        "Test cross-repo dependency cycles"
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        msg = "Depends-On: %s" % (A.data['url'],)
        B = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'B', body=msg)
        A.addApproval('Code-Review', 2)
        B.addLabel('approved')

        # A -> B -> A (via commit-depends)

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 0)
        self.assertEqual(len(B.comments), 0)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)

    def test_crd_gate_unknown(self):
        "Test unknown projects in dependent pipeline"
        self.init_repo("github/unknown", tag='init')
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest('github/unknown', 'master',
                                                 'B')
        A.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        event = B.addLabel('approved')
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        # Unknown projects cannot share a queue with any other
        # since they don't have common jobs with any other (they have no jobs).
        # Changes which depend on unknown project changes
        # should not be processed in dependent pipeline
        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)
        self.assertEqual(A.reported, 0)
        self.assertEqual(len(B.comments), 0)
        self.assertEqual(len(self.history), 0)

        # Simulate change B being gated outside this layout Set the
        # change merged before submitting the event so that when the
        # event triggers a gerrit query to update the change, we get
        # the information that it was merged.
        B.setMerged('merged')
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Now that B is merged, A should be able to be enqueued and
        # merged.
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertTrue(B.is_merged)
        self.assertEqual(len(B.comments), 0)

    def test_crd_check(self):
        "Test cross-repo dependencies in independent pipelines"
        self.executor_server.hold_jobs_in_build = True
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest(
            'github/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertTrue(self.builds[0].hasChanges(A, B))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)
        self.assertEqual(A.reported, 1)
        self.assertEqual(len(B.comments), 0)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 1,1' %
                         (B.head_sha,))

        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_duplicate(self):
        "Test duplicate check in independent pipelines"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest(
            'github/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        # Add two dependent changes...
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...make sure the live one is not duplicated...
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...but the non-live one is able to be.
        self.fake_github.emitEvent(B.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 3)

        # Release jobs in order to avoid races with change A jobs
        # finishing before change B jobs.
        self.orderedRelease()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)
        self.assertEqual(A.reported, 1)
        self.assertEqual(len(B.comments), 1)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 1,1' %
                         (B.head_sha,))

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,%s' %
                         (B.head_sha,))
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.messages[0])

    def _test_crd_check_reconfiguration(self, project1, project2):
        "Test cross-repo dependencies re-enqueued in independent pipelines"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest(
            'github/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)

        # Make sure the items still share a change queue, and the
        # first one is not live.
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 1)
        queue = tenant.layout.pipelines['check'].queues[0]
        first_item = queue.queue[0]
        for item in queue.queue:
            self.assertEqual(item.queue, first_item.queue)
        self.assertFalse(first_item.live)
        self.assertTrue(queue.queue[1].live)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertFalse(B.is_merged)
        self.assertEqual(A.reported, 1)
        self.assertEqual(len(B.comments), 0)

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,%s 1,1' %
                         (B.head_sha,))
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_reconfiguration(self):
        self._test_crd_check_reconfiguration('org/project1', 'org/project2')

    def test_crd_undefined_project(self):
        """Test that undefined projects in dependencies are handled for
        independent pipelines"""
        # It's a hack for fake github,
        # as it implies repo creation upon the creation of any change
        self.init_repo("github/unknown", tag='init')
        self._test_crd_check_reconfiguration('gerrit/project1',
                                             'github/unknown')

    def test_crd_check_transitive(self):
        "Test transitive cross-repo dependencies"
        # Specifically, if A -> B -> C, and C gets a new patchset and
        # A gets a new patchset, ensure the test of A,2 includes B,1
        # and C,2 (not C,1 which would indicate stale data in the
        # cache for B).
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        C = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'C')
        # B Depends-On: C
        msg = "Depends-On: %s" % (C.data['url'],)
        B = self.fake_github.openFakePullRequest(
            'github/project2', 'master', 'B', body=msg)

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,1 1,%s 1,1' %
                         (B.head_sha,))

        self.fake_github.emitEvent(B.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,1 1,%s' %
                         (B.head_sha,))

        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,1')

        C.addPatchset()
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,2')

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,2 1,%s 1,2' %
                         (B.head_sha,))

    def test_crd_check_unknown(self):
        "Test unknown projects in independent pipeline"
        self.init_repo("github/unknown", tag='init')
        A = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'A')
        B = self.fake_github.openFakePullRequest(
            'github/unknown', 'master', 'B')
        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)

        # Make sure zuul has seen an event on B.
        self.fake_github.emitEvent(B.getPullRequestEditedEvent())
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertFalse(B.is_merged)
        self.assertEqual(len(B.comments), 0)

    def test_crd_cycle_join(self):
        "Test an updated change creates a cycle"
        A = self.fake_github.openFakePullRequest(
            'github/project2', 'master', 'A')

        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(len(A.comments), 1)

        # Create B->A
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.url)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Dep is there so zuul should have reported on B
        self.assertEqual(B.reported, 1)

        # Update A to add A->B (a cycle).
        A.editBody('Depends-On: %s\n' % (B.data['url']))
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        # Dependency cycle injected so zuul should not have reported again on A
        self.assertEqual(len(A.comments), 1)

        # Now if we update B to remove the depends-on, everything
        # should be okay.  B; A->B

        B.addPatchset()
        B.data['commitMessage'] = '%s\n' % (B.subject,)
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        # Cycle was removed so now zuul should have reported again on A
        self.assertEqual(len(A.comments), 2)

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(B.reported, 2)


class TestGithubToGerritCRD(ZuulTestCase):
    config_file = 'zuul-gerrit-github.conf'
    tenant_config_file = 'config/cross-source/main.yaml'

    def test_crd_gate(self):
        "Test cross-repo dependencies"
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')

        B.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url']))

        event = A.addLabel('approved')
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')

        for connection in self.connections.connections.values():
            connection.maintainCache([])

        self.executor_server.hold_jobs_in_build = True
        B.addApproval('Approved', 1)
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertTrue(A.is_merged)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(len(A.comments), 2)
        self.assertEqual(B.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 1,%s' % A.head_sha)

    def test_crd_branch(self):
        "Test cross-repo dependencies in multiple branches"

        self.create_branch('gerrit/project1', 'mp')
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')
        C1 = self.fake_gerrit.addFakeChange('gerrit/project1', 'mp', 'C1')

        B.addApproval('Code-Review', 2)
        C1.addApproval('Code-Review', 2)

        # A Depends-On: B+C1
        A.editBody('Depends-On: %s\nDepends-On: %s\n' % (
            B.data['url'], C1.data['url']))

        self.executor_server.hold_jobs_in_build = True
        B.addApproval('Approved', 1)
        C1.addApproval('Approved', 1)
        self.fake_github.emitEvent(A.addLabel('approved'))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C1.data['status'], 'MERGED')
        self.assertEqual(len(A.comments), 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C1.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 2,1 1,%s' %
                         (A.head_sha,))

    def test_crd_gate_reverse(self):
        "Test reverse cross-repo dependencies"
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')
        B.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        self.fake_github.emitEvent(A.addLabel('approved'))
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')

        self.executor_server.hold_jobs_in_build = True
        A.addLabel('approved')
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertTrue(A.is_merged)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(len(A.comments), 2)
        self.assertEqual(B.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 1,%s' %
                         (A.head_sha,))

    def test_crd_cycle(self):
        "Test cross-repo dependency cycles"
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.url)

        B.addApproval('Code-Review', 2)
        B.addApproval('Approved', 1)

        # A -> B -> A (via commit-depends)
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        self.fake_github.emitEvent(A.addLabel('approved'))
        self.waitUntilSettled()

        self.assertEqual(len(A.comments), 0)
        self.assertEqual(B.reported, 0)
        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')

    def test_crd_gate_unknown(self):
        "Test unknown projects in dependent pipeline"
        self.init_repo("gerrit/unknown", tag='init')
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/unknown', 'master', 'B')
        B.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        B.addApproval('Approved', 1)
        event = A.addLabel('approved')
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        # Unknown projects cannot share a queue with any other
        # since they don't have common jobs with any other (they have no jobs).
        # Changes which depend on unknown project changes
        # should not be processed in dependent pipeline
        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(len(A.comments), 0)
        self.assertEqual(B.reported, 0)
        self.assertEqual(len(self.history), 0)

        # Simulate change B being gated outside this layout Set the
        # change merged before submitting the event so that when the
        # event triggers a gerrit query to update the change, we get
        # the information that it was merged.
        B.setMerged()
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)

        # Now that B is merged, A should be able to be enqueued and
        # merged.
        self.fake_github.emitEvent(event)
        self.waitUntilSettled()

        self.assertTrue(A.is_merged)
        self.assertEqual(len(A.comments), 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 0)

    def test_crd_check(self):
        "Test cross-repo dependencies in independent pipelines"
        self.executor_server.hold_jobs_in_build = True
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange(
            'gerrit/project1', 'master', 'B')

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertTrue(self.builds[0].hasChanges(A, B))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(len(A.comments), 1)
        self.assertEqual(B.reported, 0)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 1,%s' %
                         (A.head_sha,))

        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_duplicate(self):
        "Test duplicate check in independent pipelines"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange(
            'gerrit/project1', 'master', 'B')

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

        # Add two dependent changes...
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...make sure the live one is not duplicated...
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 2)

        # ...but the non-live one is able to be.
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(len(check_pipeline.getAllItems()), 3)

        # Release jobs in order to avoid races with change A jobs
        # finishing before change B jobs.
        self.orderedRelease()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(len(A.comments), 1)
        self.assertEqual(B.reported, 1)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 1,%s' %
                         (A.head_sha,))

        changes = self.getJobFromHistory(
            'project-merge', 'gerrit/project1').changes
        self.assertEqual(changes, '1,1')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.comments[0])

    def _test_crd_check_reconfiguration(self, project1, project2):
        "Test cross-repo dependencies re-enqueued in independent pipelines"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange(
            'gerrit/project1', 'master', 'B')

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)

        # Make sure the items still share a change queue, and the
        # first one is not live.
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 1)
        queue = tenant.layout.pipelines['check'].queues[0]
        first_item = queue.queue[0]
        for item in queue.queue:
            self.assertEqual(item.queue, first_item.queue)
        self.assertFalse(first_item.live)
        self.assertTrue(queue.queue[1].live)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(len(A.comments), 1)
        self.assertEqual(B.reported, 0)

        changes = self.getJobFromHistory(
            'project-merge', 'github/project2').changes
        self.assertEqual(changes, '1,1 1,%s' %
                         (A.head_sha,))
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_reconfiguration(self):
        self._test_crd_check_reconfiguration('org/project1', 'org/project2')

    def test_crd_undefined_project(self):
        """Test that undefined projects in dependencies are handled for
        independent pipelines"""
        # It's a hack for fake gerrit,
        # as it implies repo creation upon the creation of any change
        self.init_repo("gerrit/unknown", tag='init')
        self._test_crd_check_reconfiguration('github/project2',
                                             'gerrit/unknown')

    def test_crd_check_transitive(self):
        "Test transitive cross-repo dependencies"
        # Specifically, if A -> B -> C, and C gets a new patchset and
        # A gets a new patchset, ensure the test of A,2 includes B,1
        # and C,2 (not C,1 which would indicate stale data in the
        # cache for B).
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange('gerrit/project1', 'master', 'B')
        C = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'C')

        # B Depends-On: C
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, C.url)

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,%s 1,1 1,%s' %
                         (C.head_sha, A.head_sha))

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,%s 1,1' %
                         (C.head_sha,))

        self.fake_github.emitEvent(C.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,%s' %
                         (C.head_sha,))

        new_c_head = C.head_sha
        C.addCommit()
        old_c_head = C.head_sha
        self.assertNotEqual(old_c_head, new_c_head)
        self.fake_github.emitEvent(C.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,%s' %
                         (C.head_sha,))

        new_a_head = A.head_sha
        A.addCommit()
        old_a_head = A.head_sha
        self.assertNotEqual(old_a_head, new_a_head)
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '2,%s 1,1 1,%s' %
                         (C.head_sha, A.head_sha,))

    def test_crd_check_unknown(self):
        "Test unknown projects in independent pipeline"
        self.init_repo("gerrit/unknown", tag='init')
        A = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'A')
        B = self.fake_gerrit.addFakeChange(
            'gerrit/unknown', 'master', 'B')

        # A Depends-On: B
        A.editBody('Depends-On: %s\n' % (B.data['url'],))

        # Make sure zuul has seen an event on B.
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_github.emitEvent(A.getPullRequestEditedEvent())
        self.waitUntilSettled()

        self.assertFalse(A.is_merged)
        self.assertEqual(len(A.comments), 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 0)

    def test_crd_cycle_join(self):
        "Test an updated change creates a cycle"
        A = self.fake_gerrit.addFakeChange(
            'gerrit/project1', 'master', 'A')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1)

        # Create B->A
        B = self.fake_github.openFakePullRequest('github/project2', 'master',
                                                 'B')
        B.editBody('Depends-On: %s\n' % (A.data['url'],))
        self.fake_github.emitEvent(B.getPullRequestEditedEvent())
        self.waitUntilSettled()

        # Dep is there so zuul should have reported on B
        self.assertEqual(len(B.comments), 1)

        # Update A to add A->B (a cycle).
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.url)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Dependency cycle injected so zuul should not have reported again on A
        self.assertEqual(A.reported, 1)

        # Now if we update B to remove the depends-on, everything
        # should be okay.  B; A->B

        B.addCommit()
        B.editBody('')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Cycle was removed so now zuul should have reported again on A
        self.assertEqual(A.reported, 2)

        self.fake_github.emitEvent(B.getPullRequestEditedEvent())
        self.waitUntilSettled()
        self.assertEqual(len(B.comments), 2)
