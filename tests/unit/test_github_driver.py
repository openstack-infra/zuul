# Copyright 2015 GoodData
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

import asyncio
import threading
import os
import re
from testtools.matchers import MatchesRegex, StartsWith
import urllib
import socket
import time
from unittest import skip

import git

import zuul.web

from tests.base import ZuulTestCase, simple_layout, random_sha1


class TestGithubDriver(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_pull_event(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test1').result)
        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test2').result)

        job = self.getJobFromHistory('project-test2')
        zuulvars = job.parameters['zuul']
        self.assertEqual(str(A.number), zuulvars['change'])
        self.assertEqual(str(A.head_sha), zuulvars['patchset'])
        self.assertEqual('master', zuulvars['branch'])
        self.assertEqual(1, len(A.comments))
        self.assertThat(
            A.comments[0],
            MatchesRegex('.*\[project-test1 \]\(.*\).*', re.DOTALL))
        self.assertThat(
            A.comments[0],
            MatchesRegex('.*\[project-test2 \]\(.*\).*', re.DOTALL))
        self.assertEqual(2, len(self.history))

        # test_pull_unmatched_branch_event(self):
        self.create_branch('org/project', 'unmatched_branch')
        B = self.fake_github.openFakePullRequest(
            'org/project', 'unmatched_branch', 'B')
        self.fake_github.emitEvent(B.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        self.assertEqual(2, len(self.history))

    @simple_layout('layouts/files-github.yaml', driver='github')
    def test_pull_matched_file_event(self):
        A = self.fake_github.openFakePullRequest(
            'org/project', 'master', 'A',
            files=['random.txt', 'build-requires'])
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))

        # test_pull_unmatched_file_event
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B',
                                                 files=['random.txt'])
        self.fake_github.emitEvent(B.getPullRequestOpenedEvent())
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_comment_event(self):
        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        self.fake_github.emitEvent(A.getCommentAddedEvent('test me'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))

        # Test an unmatched comment, history should remain the same
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        self.fake_github.emitEvent(B.getCommentAddedEvent('casual comment'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))

    @simple_layout('layouts/push-tag-github.yaml', driver='github')
    def test_tag_event(self):
        self.executor_server.hold_jobs_in_build = True

        self.create_branch('org/project', 'tagbranch')
        files = {'README.txt': 'test'}
        self.addCommitToRepo('org/project', 'test tag',
                             files, branch='tagbranch', tag='newtag')
        path = os.path.join(self.upstream_root, 'org/project')
        repo = git.Repo(path)
        tag = repo.tags['newtag']
        sha = tag.commit.hexsha
        del repo

        self.fake_github.emitEvent(
            self.fake_github.getPushEvent('org/project', 'refs/tags/newtag',
                                          new_rev=sha))
        self.waitUntilSettled()

        build_params = self.builds[0].parameters
        self.assertEqual('refs/tags/newtag', build_params['zuul']['ref'])
        self.assertFalse('oldrev' in build_params['zuul'])
        self.assertEqual(sha, build_params['zuul']['newrev'])
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-tag').result)

    @simple_layout('layouts/push-tag-github.yaml', driver='github')
    def test_push_event(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        old_sha = '0' * 40
        new_sha = A.head_sha
        A.setMerged("merging A")
        pevent = self.fake_github.getPushEvent(project='org/project',
                                               ref='refs/heads/master',
                                               old_rev=old_sha,
                                               new_rev=new_sha)
        self.fake_github.emitEvent(pevent)
        self.waitUntilSettled()

        build_params = self.builds[0].parameters
        self.assertEqual('refs/heads/master', build_params['zuul']['ref'])
        self.assertFalse('oldrev' in build_params['zuul'])
        self.assertEqual(new_sha, build_params['zuul']['newrev'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-post').result)
        self.assertEqual(1, len(self.history))

        # test unmatched push event
        old_sha = random_sha1()
        new_sha = random_sha1()
        self.fake_github.emitEvent(
            self.fake_github.getPushEvent('org/project',
                                          'refs/heads/unmatched_branch',
                                          old_sha, new_sha))
        self.waitUntilSettled()

        self.assertEqual(1, len(self.history))

    @simple_layout('layouts/labeling-github.yaml', driver='github')
    def test_labels(self):
        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        self.fake_github.emitEvent(A.addLabel('test'))
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))
        self.assertEqual('project-labels', self.history[0].name)
        self.assertEqual(['tests passed'], A.labels)

        # test label removed
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        B.addLabel('do not test')
        self.fake_github.emitEvent(B.removeLabel('do not test'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))
        self.assertEqual('project-labels', self.history[1].name)
        self.assertEqual(['tests passed'], B.labels)

        # test unmatched label
        C = self.fake_github.openFakePullRequest('org/project', 'master', 'C')
        self.fake_github.emitEvent(C.addLabel('other label'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))
        self.assertEqual(['other label'], C.labels)

    @simple_layout('layouts/reviews-github.yaml', driver='github')
    def test_review_event(self):
        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        self.fake_github.emitEvent(A.getReviewAddedEvent('approve'))
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))
        self.assertEqual('project-reviews', self.history[0].name)
        self.assertEqual(['tests passed'], A.labels)

        # test_review_unmatched_event
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        self.fake_github.emitEvent(B.getReviewAddedEvent('comment'))
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))

    @simple_layout('layouts/dequeue-github.yaml', driver='github')
    def test_dequeue_pull_synchronized(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest(
            'org/one-job-project', 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        # event update stamp has resolution one second, wait so the latter
        # one has newer timestamp
        time.sleep(1)
        A.addCommit()
        self.fake_github.emitEvent(A.getPullRequestSynchronizeEvent())
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(2, len(self.history))
        self.assertEqual(1, self.countJobResults(self.history, 'ABORTED'))

    @simple_layout('layouts/dequeue-github.yaml', driver='github')
    def test_dequeue_pull_abandoned(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest(
            'org/one-job-project', 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()
        self.fake_github.emitEvent(A.getPullRequestClosedEvent())
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(1, len(self.history))
        self.assertEqual(1, self.countJobResults(self.history, 'ABORTED'))

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_git_https_url(self):
        """Test that git_ssh option gives git url with ssh"""
        tenant = self.sched.abide.tenants.get('tenant-one')
        _, project = tenant.getProject('org/project')

        url = self.fake_github.real_getGitUrl(project)
        self.assertEqual('https://github.com/org/project', url)

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_git_ssh_url(self):
        """Test that git_ssh option gives git url with ssh"""
        tenant = self.sched.abide.tenants.get('tenant-one')
        _, project = tenant.getProject('org/project')

        url = self.fake_github_ssh.real_getGitUrl(project)
        self.assertEqual('ssh://git@github.com/org/project.git', url)

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_git_enterprise_url(self):
        """Test that git_url option gives git url with proper host"""
        tenant = self.sched.abide.tenants.get('tenant-one')
        _, project = tenant.getProject('org/project')

        url = self.fake_github_ent.real_getGitUrl(project)
        self.assertEqual('ssh://git@github.enterprise.io/org/project.git', url)

    @simple_layout('layouts/reporting-github.yaml', driver='github')
    def test_reporting(self):
        project = 'org/project'
        github = self.fake_github.github_client

        # pipeline reports pull status both on start and success
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        # We should have a status container for the head sha
        self.assertIn(
            A.head_sha, github.repo_from_project(project)._commits.keys())
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)

        # We should only have one status for the head sha
        self.assertEqual(1, len(statuses))
        check_status = statuses[0]
        check_url = ('http://zuul.example.com/status/#%s,%s' %
                     (A.number, A.head_sha))
        self.assertEqual('tenant-one/check', check_status['context'])
        self.assertEqual('check status: pending',
                         check_status['description'])
        self.assertEqual('pending', check_status['state'])
        self.assertEqual(check_url, check_status['url'])
        self.assertEqual(0, len(A.comments))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        # We should only have two statuses for the head sha
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(2, len(statuses))
        check_status = statuses[0]
        check_url = ('http://zuul.example.com/status/#%s,%s' %
                     (A.number, A.head_sha))
        self.assertEqual('tenant-one/check', check_status['context'])
        self.assertEqual('check status: success',
                         check_status['description'])
        self.assertEqual('success', check_status['state'])
        self.assertEqual(check_url, check_status['url'])
        self.assertEqual(1, len(A.comments))
        self.assertThat(A.comments[0],
                        MatchesRegex('.*Build succeeded.*', re.DOTALL))

        # pipeline does not report any status but does comment
        self.executor_server.hold_jobs_in_build = True
        self.fake_github.emitEvent(
            A.getCommentAddedEvent('reporting check'))
        self.waitUntilSettled()
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(2, len(statuses))
        # comments increased by one for the start message
        self.assertEqual(2, len(A.comments))
        self.assertThat(A.comments[1],
                        MatchesRegex('.*Starting reporting jobs.*', re.DOTALL))
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        # pipeline reports success status
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(3, len(statuses))
        report_status = statuses[0]
        self.assertEqual('tenant-one/reporting', report_status['context'])
        self.assertEqual('reporting status: success',
                         report_status['description'])
        self.assertEqual('success', report_status['state'])
        self.assertEqual(2, len(A.comments))

        base = 'http://logs.example.com/tenant-one/reporting/%s/%s/' % (
            A.project, A.number)

        # Deconstructing the URL because we don't save the BuildSet UUID
        # anywhere to do a direct comparison and doing regexp matches on a full
        # URL is painful.

        # The first part of the URL matches the easy base string
        self.assertThat(report_status['url'], StartsWith(base))

        # The rest of the URL is a UUID and a trailing slash.
        self.assertThat(report_status['url'][len(base):],
                        MatchesRegex('^[a-fA-F0-9]{32}\/$'))

    @simple_layout('layouts/reporting-github.yaml', driver='github')
    def test_truncated_status_description(self):
        project = 'org/project'
        # pipeline reports pull status both on start and success
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        self.fake_github.emitEvent(
            A.getCommentAddedEvent('long pipeline'))
        self.waitUntilSettled()
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(1, len(statuses))
        check_status = statuses[0]
        # Status is truncated due to long pipeline name
        self.assertEqual('status: pending',
                         check_status['description'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        # We should only have two statuses for the head sha
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(2, len(statuses))
        check_status = statuses[0]
        # Status is truncated due to long pipeline name
        self.assertEqual('status: success',
                         check_status['description'])

    @simple_layout('layouts/reporting-github.yaml', driver='github')
    def test_push_reporting(self):
        project = 'org/project2'
        # pipeline reports pull status both on start and success
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        old_sha = '0' * 40
        new_sha = A.head_sha
        A.setMerged("merging A")
        pevent = self.fake_github.getPushEvent(project=project,
                                               ref='refs/heads/master',
                                               old_rev=old_sha,
                                               new_rev=new_sha)
        self.fake_github.emitEvent(pevent)
        self.waitUntilSettled()

        # there should only be one report, a status
        self.assertEqual(1, len(self.fake_github.reports))
        # Verify the user/context/state of the status
        status = ('zuul', 'tenant-one/push-reporting', 'pending')
        self.assertEqual(status, self.fake_github.reports[0][-1])

        # free the executor, allow the build to finish
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        # Now there should be a second report, the success of the build
        self.assertEqual(2, len(self.fake_github.reports))
        # Verify the user/context/state of the status
        status = ('zuul', 'tenant-one/push-reporting', 'success')
        self.assertEqual(status, self.fake_github.reports[-1][-1])

        # now make a PR which should also comment
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        # Now there should be a four reports, a new comment
        # and status
        self.assertEqual(4, len(self.fake_github.reports))
        self.executor_server.release()
        self.waitUntilSettled()

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_report_pull_merge(self):
        # pipeline merges the pull request on success
        A = self.fake_github.openFakePullRequest('org/project', 'master',
                                                 'PR title')
        self.fake_github.emitEvent(A.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)
        self.assertThat(A.merge_message,
                        MatchesRegex('.*PR title.*Reviewed-by.*', re.DOTALL))

        # pipeline merges the pull request on success after failure
        self.fake_github.merge_failure = True
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        self.fake_github.emitEvent(B.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertFalse(B.is_merged)
        self.fake_github.merge_failure = False

        # pipeline merges the pull request on second run of merge
        # first merge failed on 405 Method Not Allowed error
        self.fake_github.merge_not_allowed_count = 1
        C = self.fake_github.openFakePullRequest('org/project', 'master', 'C')
        self.fake_github.emitEvent(C.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(C.is_merged)

        # pipeline does not merge the pull request
        # merge failed on 405 Method Not Allowed error - twice
        self.fake_github.merge_not_allowed_count = 2
        D = self.fake_github.openFakePullRequest('org/project', 'master', 'D')
        self.fake_github.emitEvent(D.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertFalse(D.is_merged)
        self.assertEqual(len(D.comments), 1)
        self.assertEqual(D.comments[0], 'Merge failed')

    @simple_layout('layouts/reporting-multiple-github.yaml', driver='github')
    def test_reporting_multiple_github(self):
        project = 'org/project1'
        github = self.fake_github.github_client

        # pipeline reports pull status both on start and success
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest(project, 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent())
        # open one on B as well, which should not effect A reporting
        B = self.fake_github.openFakePullRequest('org/project2', 'master',
                                                 'B')
        self.fake_github.emitEvent(B.getPullRequestOpenedEvent())
        self.waitUntilSettled()
        # We should have a status container for the head sha
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertIn(
            A.head_sha, github.repo_from_project(project)._commits.keys())
        # We should only have one status for the head sha
        self.assertEqual(1, len(statuses))
        check_status = statuses[0]
        check_url = ('http://zuul.example.com/status/#%s,%s' %
                     (A.number, A.head_sha))
        self.assertEqual('tenant-one/check', check_status['context'])
        self.assertEqual('check status: pending', check_status['description'])
        self.assertEqual('pending', check_status['state'])
        self.assertEqual(check_url, check_status['url'])
        self.assertEqual(0, len(A.comments))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        # We should only have two statuses for the head sha
        statuses = self.fake_github.getCommitStatuses(project, A.head_sha)
        self.assertEqual(2, len(statuses))
        check_status = statuses[0]
        check_url = ('http://zuul.example.com/status/#%s,%s' %
                     (A.number, A.head_sha))
        self.assertEqual('tenant-one/check', check_status['context'])
        self.assertEqual('success', check_status['state'])
        self.assertEqual('check status: success', check_status['description'])
        self.assertEqual(check_url, check_status['url'])
        self.assertEqual(1, len(A.comments))
        self.assertThat(A.comments[0],
                        MatchesRegex('.*Build succeeded.*', re.DOTALL))

    @simple_layout('layouts/dependent-github.yaml', driver='github')
    def test_parallel_changes(self):
        "Test that changes are tested in parallel and merged in series"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        C = self.fake_github.openFakePullRequest('org/project', 'master', 'C')

        self.fake_github.emitEvent(A.addLabel('merge'))
        self.fake_github.emitEvent(B.addLabel('merge'))
        self.fake_github.emitEvent(C.addLabel('merge'))

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.builds[0].hasChanges(A))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))
        self.assertEqual(self.builds[2].name, 'project-merge')
        self.assertTrue(self.builds[2].hasChanges(A, B))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.builds[2].hasChanges(A))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.builds[3].hasChanges(A, B))

        self.assertEqual(self.builds[4].name, 'project-merge')
        self.assertTrue(self.builds[4].hasChanges(A, B, C))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.builds[0].hasChanges(A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.builds[1].hasChanges(A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.builds[2].hasChanges(A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.builds[3].hasChanges(A, B))

        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertTrue(self.builds[4].hasChanges(A, B, C))
        self.assertEqual(self.builds[5].name, 'project-test2')
        self.assertTrue(self.builds[5].hasChanges(A, B, C))

        all_builds = self.builds[:]
        self.release(all_builds[2])
        self.release(all_builds[3])
        self.waitUntilSettled()
        self.assertFalse(A.is_merged)
        self.assertFalse(B.is_merged)
        self.assertFalse(C.is_merged)

        self.release(all_builds[0])
        self.release(all_builds[1])
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)
        self.assertTrue(B.is_merged)
        self.assertFalse(C.is_merged)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 9)
        self.assertTrue(C.is_merged)

        self.assertNotIn('merge', A.labels)
        self.assertNotIn('merge', B.labels)
        self.assertNotIn('merge', C.labels)

    @simple_layout('layouts/dependent-github.yaml', driver='github')
    def test_failed_changes(self):
        "Test that a change behind a failed change is retested"
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')

        self.executor_server.failJob('project-test1', A)

        self.fake_github.emitEvent(A.addLabel('merge'))
        self.fake_github.emitEvent(B.addLabel('merge'))
        self.waitUntilSettled()

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()

        self.waitUntilSettled()
        # It's certain that the merge job for change 2 will run, but
        # the test1 and test2 jobs may or may not run.
        self.assertTrue(len(self.history) > 6)
        self.assertFalse(A.is_merged)
        self.assertTrue(B.is_merged)
        self.assertNotIn('merge', A.labels)
        self.assertNotIn('merge', B.labels)

    @simple_layout('layouts/dependent-github.yaml', driver='github')
    def test_failed_change_at_head(self):
        "Test that if a change at the head fails, jobs behind it are canceled"

        self.executor_server.hold_jobs_in_build = True
        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        B = self.fake_github.openFakePullRequest('org/project', 'master', 'B')
        C = self.fake_github.openFakePullRequest('org/project', 'master', 'C')

        self.executor_server.failJob('project-test1', A)

        self.fake_github.emitEvent(A.addLabel('merge'))
        self.fake_github.emitEvent(B.addLabel('merge'))
        self.fake_github.emitEvent(C.addLabel('merge'))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.builds[0].hasChanges(A))

        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()
        self.executor_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.release(self.builds[0])
        self.waitUntilSettled()

        # project-test2, project-merge for B
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 4)

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 15)
        self.assertFalse(A.is_merged)
        self.assertTrue(B.is_merged)
        self.assertTrue(C.is_merged)
        self.assertNotIn('merge', A.labels)
        self.assertNotIn('merge', B.labels)
        self.assertNotIn('merge', C.labels)

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_push_event_reconfigure(self):
        pevent = self.fake_github.getPushEvent(project='org/common-config',
                                               ref='refs/heads/master',
                                               modified_files=['zuul.yaml'])

        # record previous tenant reconfiguration time, which may not be set
        old = self.sched.tenant_last_reconfigured.get('tenant-one', 0)
        time.sleep(1)
        self.fake_github.emitEvent(pevent)
        self.waitUntilSettled()
        new = self.sched.tenant_last_reconfigured.get('tenant-one', 0)
        # New timestamp should be greater than the old timestamp
        self.assertLess(old, new)

    # TODO(jlk): Make this a more generic test for unknown project
    @skip("Skipped for rewrite of webhook handler")
    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_ping_event(self):
        # Test valid ping
        pevent = {'repository': {'full_name': 'org/project'}}
        req = self.fake_github.emitEvent(('ping', pevent))
        self.assertEqual(req.status, 200, "Ping event didn't succeed")

        # Test invalid ping
        pevent = {'repository': {'full_name': 'unknown-project'}}
        self.assertRaises(
            urllib.error.HTTPError,
            self.fake_github.emitEvent,
            ('ping', pevent),
        )


class TestGithubUnprotectedBranches(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'
    tenant_config_file = 'config/unprotected-branches/main.yaml'

    def test_unprotected_branches(self):
        tenant = self.sched.abide.tenants.get('tenant-one')

        project1 = tenant.untrusted_projects[0]
        project2 = tenant.untrusted_projects[1]

        # project1 should have parsed master
        self.assertIn('master', project1.unparsed_branch_config.keys())

        # project2 should have no parsed branch
        self.assertEqual(0, len(project2.unparsed_branch_config.keys()))


class TestGithubWebhook(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'

    def setUp(self):
        super(TestGithubWebhook, self).setUp()

        # Start the web server
        self.web = zuul.web.ZuulWeb(
            listen_address='127.0.0.1', listen_port=0,
            gear_server='127.0.0.1', gear_port=self.gearman_server.port,
            github_connections={'github': self.fake_github})
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        ws_thread = threading.Thread(target=self.web.run, args=(loop,))
        ws_thread.start()
        self.addCleanup(loop.close)
        self.addCleanup(ws_thread.join)
        self.addCleanup(self.web.stop)

        host = '127.0.0.1'
        # Wait until web server is started
        while True:
            time.sleep(0.1)
            if self.web.server is None:
                continue
            port = self.web.server.sockets[0].getsockname()[1]
            try:
                with socket.create_connection((host, port)):
                    break
            except ConnectionRefusedError:
                pass

        self.fake_github.setZuulWebPort(port)

    def tearDown(self):
        super(TestGithubWebhook, self).tearDown()

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_webhook(self):
        """Test that we can get github events via zuul-web."""

        self.executor_server.hold_jobs_in_build = True

        A = self.fake_github.openFakePullRequest('org/project', 'master', 'A')
        self.fake_github.emitEvent(A.getPullRequestOpenedEvent(),
                                   use_zuulweb=True)
        self.waitUntilSettled()

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test1').result)
        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test2').result)

        job = self.getJobFromHistory('project-test2')
        zuulvars = job.parameters['zuul']
        self.assertEqual(str(A.number), zuulvars['change'])
        self.assertEqual(str(A.head_sha), zuulvars['patchset'])
        self.assertEqual('master', zuulvars['branch'])
        self.assertEqual(1, len(A.comments))
        self.assertThat(
            A.comments[0],
            MatchesRegex('.*\[project-test1 \]\(.*\).*', re.DOTALL))
        self.assertThat(
            A.comments[0],
            MatchesRegex('.*\[project-test2 \]\(.*\).*', re.DOTALL))
        self.assertEqual(2, len(self.history))

        # test_pull_unmatched_branch_event(self):
        self.create_branch('org/project', 'unmatched_branch')
        B = self.fake_github.openFakePullRequest(
            'org/project', 'unmatched_branch', 'B')
        self.fake_github.emitEvent(B.getPullRequestOpenedEvent(),
                                   use_zuulweb=True)
        self.waitUntilSettled()

        self.assertEqual(2, len(self.history))
