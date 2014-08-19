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
import time

import git

import zuul.lib.cloner

from tests.base import ZuulTestCase

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
                        'tests/fixtures/layout-cloner.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

    def getWorkspaceRepos(self, projects):
        repos = {}
        for project in projects:
            repos[project] = git.Repo(
                os.path.join(self.workspace_root, project))
        return repos

    def getUpstreamRepos(self, projects):
        repos = {}
        for project in projects:
            repos[project] = git.Repo(
                os.path.join(self.upstream_root, project))
        return repos

    def test_cache_dir(self):
        projects = ['org/project1', 'org/project2']
        cache_root = os.path.join(self.test_root, "cache")
        for project in projects:
            upstream_repo_path = os.path.join(self.upstream_root, project)
            cache_repo_path = os.path.join(cache_root, project)
            git.Repo.clone_from(upstream_repo_path, cache_repo_path)

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(1, len(self.builds), "One build is running")

        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        B.setMerged()

        upstream = self.getUpstreamRepos(projects)
        states = [{
            'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
            'org/project2': str(upstream['org/project2'].commit('master')),
        }]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
                cache_dir=cache_root,
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct' % (project, number))

        work = self.getWorkspaceRepos(projects)
        upstream_repo_path = os.path.join(self.upstream_root, 'org/project1')
        self.assertEquals(
            work['org/project1'].remotes.origin.url,
            upstream_repo_path,
            'workspace repo origin should be upstream, not cache'
        )

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_one_branch(self):
        self.worker.hold_jobs_in_build = True

        projects = ['org/project1', 'org/project2']
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(2, len(self.builds), "Two builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             },
        ]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct' % (project, number))

            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_multi_branch(self):
        self.worker.hold_jobs_in_build = True
        projects = ['org/project1', 'org/project2',
                    'org/project3', 'org/project4']

        self.create_branch('org/project2', 'stable/havana')
        self.create_branch('org/project4', 'stable/havana')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'stable/havana',
                                           'B')
        C = self.fake_gerrit.addFakeChange('org/project3', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(3, len(self.builds), "Three builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].
                                 commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].
                                 commit('stable/havana')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             'org/project3': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].
                                 commit('master')),
             },
        ]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct' % (project, number))
            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_upgrade(self):
        # Simulates an upgrade test
        self.worker.hold_jobs_in_build = True
        projects = ['org/project1', 'org/project2', 'org/project3',
                    'org/project4', 'org/project5', 'org/project6']

        self.create_branch('org/project2', 'stable/havana')
        self.create_branch('org/project3', 'stable/havana')
        self.create_branch('org/project4', 'stable/havana')
        self.create_branch('org/project5', 'stable/havana')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project3', 'stable/havana',
                                           'C')
        D = self.fake_gerrit.addFakeChange('org/project3', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project4', 'stable/havana',
                                           'E')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(5, len(self.builds), "Five builds are running")

        # Check the old side of the upgrade first
        upstream = self.getUpstreamRepos(projects)
        states = [
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit(
                                 'stable/havana')),
             'org/project3': str(upstream['org/project3'].commit(
                                 'stable/havana')),
             'org/project4': str(upstream['org/project4'].commit(
                                 'stable/havana')),
             'org/project5': str(upstream['org/project5'].commit(
                                 'stable/havana')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit(
                                 'stable/havana')),
             'org/project3': str(upstream['org/project3'].commit(
                                 'stable/havana')),
             'org/project4': str(upstream['org/project4'].commit(
                                 'stable/havana')),
             'org/project5': str(upstream['org/project5'].commit(
                                 'stable/havana')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit(
                                 'stable/havana')),
             'org/project3': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].commit(
                                 'stable/havana')),

             'org/project5': str(upstream['org/project5'].commit(
                                 'stable/havana')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit(
                                 'stable/havana')),
             'org/project3': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].commit(
                                 'stable/havana')),
             'org/project5': str(upstream['org/project5'].commit(
                                 'stable/havana')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit(
                                 'stable/havana')),
             'org/project3': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project4': self.builds[4].parameters['ZUUL_COMMIT'],
             'org/project5': str(upstream['org/project5'].commit(
                                 'stable/havana')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
        ]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
                branch='stable/havana',  # Old branch for upgrade
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct on old side of upgrade' %
                                  (project, number))
            shutil.rmtree(self.workspace_root)

        # Check the new side of the upgrade
        states = [
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project3': self.builds[3].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project3': self.builds[3].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
        ]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
                branch='master',  # New branch for upgrade
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct on old side of upgrade' %
                                  (project, number))
            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_project_override(self):
        self.worker.hold_jobs_in_build = True
        projects = ['org/project1', 'org/project2', 'org/project3',
                    'org/project4', 'org/project5', 'org/project6']

        self.create_branch('org/project3', 'stable/havana')
        self.create_branch('org/project4', 'stable/havana')
        self.create_branch('org/project6', 'stable/havana')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project3', 'stable/havana',
                                           'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEquals(4, len(self.builds), "Four builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {'org/project1': self.builds[0].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project2': str(upstream['org/project2'].commit('master')),
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project3': str(upstream['org/project3'].commit('master')),
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit('master')),
             },
            {'org/project1': self.builds[1].parameters['ZUUL_COMMIT'],
             'org/project2': self.builds[2].parameters['ZUUL_COMMIT'],
             'org/project3': self.builds[3].parameters['ZUUL_COMMIT'],
             'org/project4': str(upstream['org/project4'].commit('master')),
             'org/project5': str(upstream['org/project5'].commit('master')),
             'org/project6': str(upstream['org/project6'].commit(
                                 'stable/havana')),
             },
        ]

        for number, build in enumerate(self.builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters['ZUUL_BRANCH'],
                zuul_ref=build.parameters['ZUUL_REF'],
                zuul_url=self.git_root,
                project_branches={'org/project4': 'master'},
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct' % (project, number))
            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_periodic(self):
        self.worker.hold_jobs_in_build = True
        self.create_branch('org/project', 'stable/havana')
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        builds = self.builds[:]

        self.worker.hold_jobs_in_build = False
        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()
        self.worker.release()
        self.waitUntilSettled()

        projects = ['org/project']

        self.assertEquals(2, len(builds), "Two builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {'org/project':
                str(upstream['org/project'].commit('stable/havana')),
             },
            {'org/project':
                str(upstream['org/project'].commit('stable/havana')),
             },
        ]

        for number, build in enumerate(builds):
            self.log.debug("Build parameters: %s", build.parameters)
            cloner = zuul.lib.cloner.Cloner(
                git_base_url=self.upstream_root,
                projects=projects,
                workspace=self.workspace_root,
                zuul_branch=build.parameters.get('ZUUL_BRANCH', None),
                zuul_ref=build.parameters.get('ZUUL_REF', None),
                zuul_url=self.git_root,
                branch='stable/havana',
            )
            cloner.execute()
            work = self.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertEquals(state[project],
                                  str(work[project].commit('HEAD')),
                                  'Project %s commit for build %s should '
                                  'be correct' % (project, number))

            shutil.rmtree(self.workspace_root)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
