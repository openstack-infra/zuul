#!/usr/bin/env python

# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from tests.base import ZuulTestCase


class TestZuulTriggerParentChangeEnqueued(ZuulTestCase):
    tenant_config_file = 'config/zuultrigger/parent-change-enqueued/main.yaml'

    def test_zuul_trigger_parent_change_enqueued(self):
        "Test Zuul trigger event: parent-change-enqueued"
        # This test has the following three changes:
        # B1 -> A; B2 -> A
        # When A is enqueued in the gate, B1 and B2 should both attempt
        # to be enqueued in both pipelines.  B1 should end up in check
        # and B2 in gate because of differing pipeline requirements.
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'B1')
        B2 = self.fake_gerrit.addFakeChange('org/project', 'master', 'B2')
        A.addApproval('Code-Review', 2)
        B1.addApproval('Code-Review', 2)
        B2.addApproval('Code-Review', 2)
        A.addApproval('Verified', 1)    # required by gate
        B1.addApproval('Verified', -1)  # should go to check
        B2.addApproval('Verified', 1)   # should go to gate
        B1.addApproval('Approved', 1)
        B2.addApproval('Approved', 1)
        B1.setDependsOn(A, 1)
        B2.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        # Jobs are being held in build to make sure that 3,1 has time
        # to enqueue behind 1,1 so that the test is more
        # deterministic.
        self.waitUntilSettled()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 3)
        for job in self.history:
            if job.changes == '1,1':
                self.assertEqual(job.name, 'project-gate')
            elif job.changes == '1,1 2,1':
                self.assertEqual(job.name, 'project-check')
            elif job.changes == '1,1 3,1':
                self.assertEqual(job.name, 'project-gate')
            else:
                raise Exception("Unknown job")


class TestZuulTriggerProjectChangeMerged(ZuulTestCase):

    tenant_config_file = 'config/zuultrigger/project-change-merged/main.yaml'

    def test_zuul_trigger_project_change_merged(self):
        # This test has the following three changes:
        # A, B, C;  B conflicts with A, but C does not.
        # When A is merged, B and C should be checked for conflicts,
        # and B should receive a -1.
        # D and E are used to repeat the test in the second part, but
        # are defined here to that they end up in the trigger cache.
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        A.addPatchset({'conflict': 'foo'})
        B.addPatchset({'conflict': 'bar'})
        D.addPatchset({'conflict2': 'foo'})
        E.addPatchset({'conflict2': 'bar'})
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project-gate')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 0)
        self.assertEqual(D.reported, 0)
        self.assertEqual(E.reported, 0)
        self.assertEqual(
            B.messages[0],
            "Merge Failed.\n\nThis change or one of its cross-repo "
            "dependencies was unable to be automatically merged with the "
            "current state of its repository. Please rebase the change and "
            "upload a new patchset.")

        self.assertTrue("project:org/project status:open" in
                        self.fake_gerrit.queries)

        # Reconfigure and run the test again.  This is a regression
        # check to make sure that we don't end up with a stale trigger
        # cache that has references to projects from the old
        # configuration.
        self.sched.reconfigure(self.config)

        D.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, 'project-gate')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 0)
        self.assertEqual(D.reported, 2)
        self.assertEqual(E.reported, 1)
        self.assertEqual(
            E.messages[0],
            "Merge Failed.\n\nThis change or one of its cross-repo "
            "dependencies was unable to be automatically merged with the "
            "current state of its repository. Please rebase the change and "
            "upload a new patchset.")
        self.assertIn("project:org/project status:open",
                      self.fake_gerrit.queries)
