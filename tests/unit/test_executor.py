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
import time
from unittest import mock

import zuul.executor.server
import zuul.model

from tests.base import ZuulTestCase, simple_layout, iterate_timeout
from zuul.executor.sensors.startingbuilds import StartingBuildsSensor


class TestExecutorRepos(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    log = logging.getLogger("zuul.test.executor")

    def assertRepoState(self, repo, state, project, build, number):
        if 'branch' in state:
            self.assertFalse(repo.head.is_detached,
                             'Project %s commit for build %s #%s should '
                             'not have a detached HEAD' % (
                                 project, build, number))
            self.assertEqual(repo.active_branch.name,
                             state['branch'],
                             'Project %s commit for build %s #%s should '
                             'be on the correct branch' % (
                                 project, build, number))
            # Remote 'origin' needs to be kept intact with a bogus URL
            self.assertEqual(repo.remotes.origin.url, 'file:///dev/null')
            self.assertIn(state['branch'], repo.remotes.origin.refs)
        if 'commit' in state:
            self.assertEqual(state['commit'],
                             str(repo.commit('HEAD')),
                             'Project %s commit for build %s #%s should '
                             'be correct' % (
                                 project, build, number))
        ref = repo.commit('HEAD')
        repo_messages = set(
            [c.message.strip() for c in repo.iter_commits(ref)])
        if 'present' in state:
            for change in state['present']:
                msg = '%s-1' % change.subject
                self.assertTrue(msg in repo_messages,
                                'Project %s for build %s #%s should '
                                'have change %s' % (
                                    project, build, number, change.subject))
        if 'absent' in state:
            for change in state['absent']:
                msg = '%s-1' % change.subject
                self.assertTrue(msg not in repo_messages,
                                'Project %s for build %s #%s should '
                                'not have change %s' % (
                                    project, build, number, change.subject))

    def assertBuildStates(self, states, projects):
        for number, build in enumerate(self.builds):
            work = build.getWorkspaceRepos(projects)
            state = states[number]

            for project in projects:
                self.assertRepoState(work[project], state[project],
                                     project, build, number)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/repo-checkout-two-project.yaml')
    def test_one_branch(self):
        self.executor_server.hold_jobs_in_build = True

        p1 = 'review.example.com/org/project1'
        p2 = 'review.example.com/org/project2'
        projects = [p1, p2]
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'master', 'B')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(2, len(self.builds), "Two builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {p1: dict(present=[A], absent=[B], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      branch='master'),
             },
            {p1: dict(present=[A], absent=[B], branch='master'),
             p2: dict(present=[B], absent=[A], branch='master'),
             },
        ]

        self.assertBuildStates(states, projects)

    @simple_layout('layouts/repo-checkout-four-project.yaml')
    def test_multi_branch(self):
        self.executor_server.hold_jobs_in_build = True

        p1 = 'review.example.com/org/project1'
        p2 = 'review.example.com/org/project2'
        p3 = 'review.example.com/org/project3'
        p4 = 'review.example.com/org/project4'
        projects = [p1, p2, p3, p4]

        self.create_branch('org/project2', 'stable/havana')
        self.create_branch('org/project4', 'stable/havana')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project2', 'stable/havana',
                                           'B')
        C = self.fake_gerrit.addFakeChange('org/project3', 'master', 'C')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(3, len(self.builds), "Three builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {p1: dict(present=[A], absent=[B, C], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      branch='master'),
             p3: dict(commit=str(upstream[p3].commit('master')),
                      branch='master'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             },
            {p1: dict(present=[A], absent=[B, C], branch='master'),
             p2: dict(present=[B], absent=[A, C], branch='stable/havana'),
             p3: dict(commit=str(upstream[p3].commit('master')),
                      branch='master'),
             p4: dict(commit=str(upstream[p4].commit('stable/havana')),
                      branch='stable/havana'),
             },
            {p1: dict(present=[A], absent=[B, C], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      branch='master'),
             p3: dict(present=[C], absent=[A, B], branch='master'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             },
        ]

        self.assertBuildStates(states, projects)

    @simple_layout('layouts/repo-checkout-six-project.yaml')
    def test_project_override(self):
        self.executor_server.hold_jobs_in_build = True

        p1 = 'review.example.com/org/project1'
        p2 = 'review.example.com/org/project2'
        p3 = 'review.example.com/org/project3'
        p4 = 'review.example.com/org/project4'
        p5 = 'review.example.com/org/project5'
        p6 = 'review.example.com/org/project6'
        projects = [p1, p2, p3, p4, p5, p6]

        self.create_branch('org/project3', 'stable/havana')
        self.create_branch('org/project4', 'stable/havana')
        self.create_branch('org/project6', 'stable/havana')
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project3', 'stable/havana',
                                           'D')
        A.addApproval('Code-Review', 2)
        B.addApproval('Code-Review', 2)
        C.addApproval('Code-Review', 2)
        D.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(C.addApproval('Approved', 1))
        self.fake_gerrit.addEvent(D.addApproval('Approved', 1))

        self.waitUntilSettled()

        self.assertEqual(4, len(self.builds), "Four builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {p1: dict(present=[A], absent=[B, C, D], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      branch='master'),
             p3: dict(commit=str(upstream[p3].commit('master')),
                      branch='master'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             p5: dict(commit=str(upstream[p5].commit('master')),
                      branch='master'),
             p6: dict(commit=str(upstream[p6].commit('master')),
                      branch='master'),
             },
            {p1: dict(present=[A, B], absent=[C, D], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      branch='master'),
             p3: dict(commit=str(upstream[p3].commit('master')),
                      branch='master'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             p5: dict(commit=str(upstream[p5].commit('master')),
                      branch='master'),
             p6: dict(commit=str(upstream[p6].commit('master')),
                      branch='master'),
             },
            {p1: dict(present=[A, B], absent=[C, D], branch='master'),
             p2: dict(present=[C], absent=[A, B, D], branch='master'),
             p3: dict(commit=str(upstream[p3].commit('master')),
                      branch='master'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             p5: dict(commit=str(upstream[p5].commit('master')),
                      branch='master'),
             p6: dict(commit=str(upstream[p6].commit('master')),
                      branch='master'),
             },
            {p1: dict(present=[A, B], absent=[C, D], branch='master'),
             p2: dict(present=[C], absent=[A, B, D], branch='master'),
             p3: dict(present=[D], absent=[A, B, C],
                      branch='stable/havana'),
             p4: dict(commit=str(upstream[p4].commit('master')),
                      branch='master'),
             p5: dict(commit=str(upstream[p5].commit('master')),
                      branch='master'),
             p6: dict(commit=str(upstream[p6].commit('stable/havana')),
                      branch='stable/havana'),
             },
        ]

        self.assertBuildStates(states, projects)

    def test_periodic_override(self):
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.

        # This tests that we can override the branch in a timer
        # trigger (mostly to ensure backwards compatability for jobs).
        self.executor_server.hold_jobs_in_build = True
        # Start timer trigger - also org/project
        self.commitConfigUpdate('common-config',
                                'layouts/repo-checkout-timer-override.yaml')
        self.sched.reconfigure(self.config)

        p1 = 'review.example.com/org/project1'
        projects = [p1]
        self.create_branch('org/project1', 'stable/havana')

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.commitConfigUpdate('common-config',
                                'layouts/repo-checkout-no-timer-override.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()

        self.assertEqual(1, len(self.builds), "One build is running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {p1: dict(commit=str(upstream[p1].commit('stable/havana')),
                      branch='stable/havana'),
             },
        ]

        self.assertBuildStates(states, projects)

    def test_periodic(self):
        # This test can not use simple_layout because it must start
        # with a configuration which does not include a
        # timer-triggered job so that we have an opportunity to set
        # the hold flag before the first job.
        self.executor_server.hold_jobs_in_build = True
        # Start timer trigger - also org/project
        self.commitConfigUpdate('common-config',
                                'layouts/repo-checkout-timer.yaml')
        self.sched.reconfigure(self.config)

        p1 = 'review.example.com/org/project1'
        projects = [p1]
        self.create_branch('org/project1', 'stable/havana')

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()

        # Stop queuing timer triggered jobs so that the assertions
        # below don't race against more jobs being queued.
        self.commitConfigUpdate('common-config',
                                'layouts/repo-checkout-no-timer.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()
        # If APScheduler is in mid-event when we remove the job, we
        # can end up with one more event firing, so give it an extra
        # second to settle.
        time.sleep(1)
        self.waitUntilSettled()

        self.assertEqual(2, len(self.builds), "Two builds are running")

        upstream = self.getUpstreamRepos(projects)
        states = [
            {p1: dict(commit=str(upstream[p1].commit('stable/havana')),
                      branch='stable/havana'),
             },
            {p1: dict(commit=str(upstream[p1].commit('master')),
                      branch='master'),
             },
        ]
        if self.builds[0].parameters['zuul']['ref'] == 'refs/heads/master':
            states = list(reversed(states))

        self.assertBuildStates(states, projects)

    @simple_layout('layouts/repo-checkout-post.yaml')
    def test_post_and_master_checkout(self):
        self.executor_server.hold_jobs_in_build = True
        p1 = "review.example.com/org/project1"
        p2 = "review.example.com/org/project2"
        projects = [p1, p2]
        upstream = self.getUpstreamRepos(projects)

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        event = A.getRefUpdatedEvent()
        A.setMerged()
        A_commit = str(upstream[p1].commit('master'))
        self.log.debug("A commit: %s" % A_commit)

        # Add another commit to the repo that merged right after this
        # one to make sure that our post job runs with the one that we
        # intended rather than simply the current repo state.
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B',
                                           parent='refs/changes/1/1/1')
        B.setMerged()
        B_commit = str(upstream[p1].commit('master'))
        self.log.debug("B commit: %s" % B_commit)

        self.fake_gerrit.addEvent(event)
        self.waitUntilSettled()

        states = [
            {p1: dict(commit=A_commit,
                      present=[A], absent=[B], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('master')),
                      absent=[A, B], branch='master'),
             },
        ]

        self.assertBuildStates(states, projects)

    @simple_layout('layouts/repo-checkout-tag.yaml')
    def test_tag_checkout(self):
        self.executor_server.hold_jobs_in_build = True
        p1 = "review.example.com/org/project1"
        p2 = "review.example.com/org/project2"
        projects = [p1, p2]
        upstream = self.getUpstreamRepos(projects)

        self.create_branch('org/project2', 'stable/havana')
        files = {'README': 'tagged readme'}
        self.addCommitToRepo('org/project2', 'tagged commit',
                             files, branch='stable/havana', tag='test-tag')

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        states = [
            {p1: dict(present=[A], branch='master'),
             p2: dict(commit=str(upstream[p2].commit('test-tag')),
                      absent=[A]),
             },
        ]

        self.assertBuildStates(states, projects)


class TestAnsibleJob(ZuulTestCase):
    tenant_config_file = 'config/ansible/main.yaml'

    def setUp(self):
        super(TestAnsibleJob, self).setUp()
        job = zuul.model.Job('test')
        job.unique = 'test'
        self.test_job = zuul.executor.server.AnsibleJob(self.executor_server,
                                                        job)

    def test_getHostList_host_keys(self):
        # Test without connection_port set
        node = {'name': 'fake-host',
                'host_keys': ['fake-host-key'],
                'interface_ip': 'localhost'}
        keys = self.test_job.getHostList({'nodes': [node],
                                          'host_vars': {}})[0]['host_keys']
        self.assertEqual(keys[0], 'localhost fake-host-key')

        # Test with custom connection_port set
        node['connection_port'] = 22022
        keys = self.test_job.getHostList({'nodes': [node],
                                          'host_vars': {}})[0]['host_keys']
        self.assertEqual(keys[0], '[localhost]:22022 fake-host-key')


class TestExecutorHostname(ZuulTestCase):
    config_file = 'zuul-executor-hostname.conf'
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_executor_hostname(self):
        self.assertEqual('test-executor-hostname.example.com',
                         self.executor_server.hostname)


class TestGovernor(ZuulTestCase):
    config_file = 'zuul-executor-hostname.conf'
    tenant_config_file = 'config/governor/main.yaml'

    @mock.patch('os.getloadavg')
    @mock.patch('psutil.virtual_memory')
    def test_load_governor(self, vm_mock, loadavg_mock):
        class Dummy(object):
            pass
        ram = Dummy()
        ram.percent = 20.0  # 20% used
        vm_mock.return_value = ram
        loadavg_mock.return_value = (0.0, 0.0, 0.0)
        self.executor_server.manageLoad()
        self.assertTrue(self.executor_server.accepting_work)
        ram.percent = 99.0  # 99% used
        loadavg_mock.return_value = (100.0, 100.0, 100.0)
        self.executor_server.manageLoad()
        self.assertFalse(self.executor_server.accepting_work)

    @mock.patch('os.statvfs')
    def test_hdd_governor(self, statvfs_mock):
        class Dummy(object):
            pass
        hdd = Dummy()
        hdd.f_frsize = 4096
        hdd.f_blocks = 120920708
        hdd.f_bfree = 95716701
        statvfs_mock.return_value = hdd  # 20.84% used

        self.executor_server.manageLoad()
        self.assertTrue(self.executor_server.accepting_work)

        self.assertReportedStat(
            'zuul.executor.test-executor-hostname_example_com.pct_used_hdd',
            value='2084', kind='g')

        hdd.f_bfree = 5716701
        statvfs_mock.return_value = hdd  # 95.27% used

        self.executor_server.manageLoad()
        self.assertFalse(self.executor_server.accepting_work)

        self.assertReportedStat(
            'zuul.executor.test-executor-hostname_example_com.pct_used_hdd',
            value='9527', kind='g')

    def test_pause_governor(self):
        self.executor_server.manageLoad()
        self.assertTrue(self.executor_server.accepting_work)

        self.executor_server.pause_sensor.pause = True
        self.executor_server.manageLoad()
        self.assertFalse(self.executor_server.accepting_work)

    def waitForExecutorBuild(self, jobname):
        self.log.debug("Waiting for %s to start", jobname)
        timeout = time.time() + 30
        build = None
        while (time.time() < timeout and not build):
            for b in self.builds:
                if b.name == jobname:
                    build = b
                    break
            time.sleep(0.1)
        self.log.debug("Found build %s", jobname)
        build_id = build.uuid
        while (time.time() < timeout and
               build_id not in self.executor_server.job_workers):
            time.sleep(0.1)
        worker = self.executor_server.job_workers[build_id]
        self.log.debug("Found worker %s", jobname)
        while (time.time() < timeout and
               not worker.started):
            time.sleep(0.1)
        self.log.debug("Worker for %s started: %s", jobname, worker.started)
        return build

    def test_slow_start(self):

        def _set_starting_builds(min, max):
            for sensor in self.executor_server.sensors:
                if isinstance(sensor, StartingBuildsSensor):
                    sensor.min_starting_builds = min
                    sensor.max_starting_builds = max

        # Note: This test relies on the fact that manageLoad is only
        # run at specific points.  Several times in the test we check
        # that manageLoad has disabled or enabled job acceptance based
        # on the number of "starting" jobs.  Some of those jobs may
        # have actually moved past the "starting" phase and are
        # actually "running".  But because manageLoad hasn't run
        # again, it still uses the old values.  Keep this in mind when
        # double checking its calculations.
        #
        # Disable the periodic governor runs to make sure they don't
        # interefere (only possible if the test runs longer than 10
        # seconds).
        self.executor_server.governor_stop_event.set()
        self.executor_server.hold_jobs_in_build = True
        _set_starting_builds(1, 1)
        self.executor_server.manageLoad()
        self.assertTrue(self.executor_server.accepting_work)
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        build1 = self.waitForExecutorBuild('test1')
        # With one job (test1) being started, we should no longer
        # be accepting new work
        self.assertFalse(self.executor_server.accepting_work)
        self.assertEqual(len(self.executor_server.job_workers), 1)
        # Allow enough starting builds for the test to complete.
        _set_starting_builds(1, 3)
        # We must wait for build1 to enter a waiting state otherwise
        # the subsequent release() is a noop and the build is never
        # released.  We don't use waitUntilSettled as that requires
        # the other two builds to start which can't happen while we
        # don't accept jobs.
        for x in iterate_timeout(30, "build1 is waiting"):
            if build1.waiting:
                break
        build1.release()
        for x in iterate_timeout(30, "Wait for build1 to complete"):
            if build1.uuid not in self.executor_server.job_workers:
                break
        self.executor_server.manageLoad()
        # This manageLoad call has determined that there are 0 workers
        # running, so our full complement of 3 starting builds is
        # available.  It will re-register for work and pick up the
        # next two jobs.

        self.waitForExecutorBuild('test2')
        self.waitForExecutorBuild('test3')
        # When each of these jobs started, they caused manageLoad to
        # be called, the second invocation calculated that there were
        # 2 workers running, so our starting build limit was reduced
        # to 1.  Usually it will calculate that there are 2 starting
        # builds, but theoretically it could count only 1 if the first
        # build manages to leave the starting phase before the second
        # build starts.  It should always count the second build as
        # starting.  As long as at least one build is still in the
        # starting phase, this will exceed the limit and unregister.
        self.assertFalse(self.executor_server.accepting_work)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.executor_server.manageLoad()
        self.assertTrue(self.executor_server.accepting_work)
