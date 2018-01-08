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

from tests.base import (
    ZuulTestCase,
    simple_layout,
)


class TestGerritLegacyCRD(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_crd_gate(self):
        "Test cross-repo dependencies"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

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

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        for connection in self.connections.connections.values():
            connection.maintainCache([])

        self.executor_server.hold_jobs_in_build = True
        B.addApproval('Approved', 1)
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
        self.assertEqual(BM2.queried, 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'org/project1').changes
        self.assertEqual(changes, '2,1 1,1')

    def test_crd_branch(self):
        "Test cross-repo dependencies in multiple branches"

        self.create_branch('org/project2', 'mp')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C1 = self.fake_gerrit.addFakeChange('org/project2', 'mp', 'C1')
        C2 = self.fake_gerrit.addFakeChange('org/project2', 'mp', 'C2',
                                            status='ABANDONED')
        C1.data['id'] = B.data['id']
        C2.data['id'] = B.data['id']

        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C1.addApproval('Code-Review', 2)

        # A Depends-On: B+C1
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.executor_server.hold_jobs_in_build = True
        B.addApproval('Approved', 1)
        C1.addApproval('Approved', 1)
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
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C1.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C1.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'org/project1').changes
        self.assertEqual(changes, '2,1 3,1 1,1')

    def test_crd_multiline(self):
        "Test multiple depends-on lines in commit"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)

        # A Depends-On: B+C
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\nDepends-On: %s\n' % (
            A.subject, B.data['id'], C.data['id'])

        self.executor_server.hold_jobs_in_build = True
        B.addApproval('Approved', 1)
        C.addApproval('Approved', 1)
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
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'org/project1').changes
        self.assertEqual(changes, '2,1 3,1 1,1')

    def test_crd_unshared_gate(self):
        "Test cross-repo dependencies in unshared gate queues"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        # A and B do not share a queue, make sure that A is unable to
        # enqueue B (and therefore, A is unable to be enqueued).
        B.addApproval('Approved', 1)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 0)
        self.assertEqual(B.reported, 0)
        self.assertEqual(len(self.history), 0)

        # Enqueue and merge B alone.
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

        # Now that B is merged, A should be able to be enqueued and
        # merged.
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_crd_gate_reverse(self):
        "Test reverse cross-repo dependencies"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        # A Depends-On: B

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        self.executor_server.hold_jobs_in_build = True
        A.addApproval('Approved', 1)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

        changes = self.getJobFromHistory(
            'project-merge', 'org/project1').changes
        self.assertEqual(changes, '2,1 1,1')

    def test_crd_cycle(self):
        "Test cross-repo dependency cycles"
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        # A -> B -> A (via commit-depends)

        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])

        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 0)
        self.assertEqual(B.reported, 0)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

    def test_crd_gate_unknown(self):
        "Test unknown projects in dependent pipeline"
        self.init_repo("org/unknown", tag='init')
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/unknown', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        B.addApproval('Approved', 1)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        # Unknown projects cannot share a queue with any other
        # since they don't have common jobs with any other (they have no jobs).
        # Changes which depend on unknown project changes
        # should not be processed in dependent pipeline
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 0)
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
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 0)

    def test_crd_check(self):
        "Test cross-repo dependencies in independent pipelines"

        self.executor_server.hold_jobs_in_build = True
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

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
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)

        self.assertEqual(self.history[0].changes, '2,1 1,1')
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_git_depends(self):
        "Test single-repo dependencies in independent pipelines"
        self.gearman_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')

        # Add two git-dependent changes and make sure they both report
        # success.
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.orderedRelease()
        self.gearman_server.hold_jobs_in_build = False
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)

        self.assertEqual(self.history[0].changes, '1,1')
        self.assertEqual(self.history[-1].changes, '1,1 2,1')
        tenant = self.sched.abide.tenants.get('tenant-one')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.messages[0])
        self.assertIn('Build succeeded', B.messages[0])

    def test_crd_check_duplicate(self):
        "Test duplicate check in independent pipelines"
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']

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

        # Release jobs in order to avoid races with change A jobs
        # finishing before change B jobs.
        self.orderedRelease()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)

        self.assertEqual(self.history[0].changes, '1,1 2,1')
        self.assertEqual(self.history[1].changes, '1,1')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

        self.assertIn('Build succeeded', A.messages[0])
        self.assertIn('Build succeeded', B.messages[0])

    def _test_crd_check_reconfiguration(self, project1, project2):
        "Test cross-repo dependencies re-enqueued in independent pipelines"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange(project1, 'master', 'A')
        B = self.fake_gerrit.addFakeChange(project2, 'master', 'B')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

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
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 0)

        self.assertEqual(self.history[0].changes, '2,1 1,1')
        self.assertEqual(len(tenant.layout.pipelines['check'].queues), 0)

    def test_crd_check_reconfiguration(self):
        self._test_crd_check_reconfiguration('org/project1', 'org/project2')

    def test_crd_undefined_project(self):
        """Test that undefined projects in dependencies are handled for
        independent pipelines"""
        # It's a hack for fake gerrit,
        # as it implies repo creation upon the creation of any change
        self.init_repo("org/unknown", tag='init')
        self._test_crd_check_reconfiguration('org/project1', 'org/unknown')

    @simple_layout('layouts/ignore-dependencies.yaml')
    def test_crd_check_ignore_dependencies(self):
        "Test cross-repo dependencies can be ignored"

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
        tenant = self.sched.abide.tenants.get('tenant-one')
        check_pipeline = tenant.layout.pipelines['check']
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

    @simple_layout('layouts/three-projects.yaml')
    def test_crd_check_transitive(self):
        "Test transitive cross-repo dependencies"
        # Specifically, if A -> B -> C, and C gets a new patchset and
        # A gets a new patchset, ensure the test of A,2 includes B,1
        # and C,2 (not C,1 which would indicate stale data in the
        # cache for B).
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project3', 'master', 'C')

        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        # B Depends-On: C
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, C.data['id'])

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '3,1 2,1 1,1')

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '3,1 2,1')

        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '3,1')

        C.addPatchset()
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '3,2')

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(self.history[-1].changes, '3,2 2,1 1,2')

    def test_crd_check_unknown(self):
        "Test unknown projects in independent pipeline"
        self.init_repo("org/unknown", tag='init')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/unknown', 'master', 'D')
        # A Depends-On: B
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])

        # Make sure zuul has seen an event on B.
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 0)

    def test_crd_cycle_join(self):
        "Test an updated change creates a cycle"
        A = self.fake_gerrit.addFakeChange('org/project2', 'master', 'A')

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.assertEqual(A.reported, 1)

        # Create B->A
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            B.subject, A.data['id'])
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Dep is there so zuul should have reported on B
        self.assertEqual(B.reported, 1)

        # Update A to add A->B (a cycle).
        A.addPatchset()
        A.data['commitMessage'] = '%s\n\nDepends-On: %s\n' % (
            A.subject, B.data['id'])
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        # Dependency cycle injected so zuul should not have reported again on A
        self.assertEqual(A.reported, 1)

        # Now if we update B to remove the depends-on, everything
        # should be okay.  B; A->B

        B.addPatchset()
        B.data['commitMessage'] = '%s\n' % (B.subject,)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        # Cycle was removed so now zuul should have reported again on A
        self.assertEqual(A.reported, 2)

        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()
        self.assertEqual(B.reported, 2)
