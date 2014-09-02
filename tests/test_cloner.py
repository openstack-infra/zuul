#!/usr/bin/env python

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2014 Wikimedia Foundation Inc.
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
import os
import shutil

import git

import zuul.lib.cloner

from tests.base import ZuulTestCase
from tests.base import FIXTURE_DIR

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


class TestCloner(ZuulTestCase):

    log = logging.getLogger("zuul.test.cloner")
    workspace_root = None

    def setUp(self):
        super(TestCloner, self).setUp()
        self.workspace_root = os.path.join(self.test_root, 'workspace')

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-gating.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

    def test_cloner(self):
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(2, len(self.builds), "Two builds are running")

        for build in self.builds:
            self.log.debug("Build parameters: %s", build.parameters)
            change_number = int(build.parameters['ZUUL_CHANGE'])
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=['org/project1', 'org/project2'],
                workspace=self.workspace_root,
                zuul_branch='master',
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
                branch='master',
            )
            cloner.execute()
            work_repo1 = git.Repo(os.path.join(self.workspace_root,
                                               'org/project1'))
            work_repo2 = git.Repo(os.path.join(self.workspace_root,
                                               'org/project2'))
            if change_number >= 1:
                self.assertEquals(
                    self.builds[0].parameters['ZUUL_COMMIT'],
                    str(work_repo1.commit('HEAD')))
            if change_number >= 2:
                self.assertEquals(
                    self.builds[1].parameters['ZUUL_COMMIT'],
                    str(work_repo2.commit('HEAD')))
            else:
                self.assertEquals(str(work_repo2.commit('master')),
                                  str(work_repo2.commit('HEAD')))
            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
