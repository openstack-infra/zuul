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

import logging
import re
from testtools.matchers import MatchesRegex

from tests.base import ZuulTestCase, simple_layout, random_sha1

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


class TestGithubDriver(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_pull_event(self):
        self.executor_server.hold_jobs_in_build = True

        pr = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(pr.getPullRequestOpenedEvent())
        self.waitUntilSettled()

        build_params = self.builds[0].parameters
        self.assertEqual('master', build_params['ZUUL_BRANCH'])
        self.assertEqual(str(pr.number), build_params['ZUUL_CHANGE'])
        self.assertEqual(pr.head_sha, build_params['ZUUL_PATCHSET'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test1').result)
        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-test2').result)

        job = self.getJobFromHistory('project-test2')
        zuulvars = job.parameters['vars']['zuul']
        self.assertEqual(pr.number, zuulvars['change'])
        self.assertEqual(pr.head_sha, zuulvars['patchset'])
        self.assertEqual(1, len(pr.comments))

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_comment_event(self):
        pr = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(pr.getCommentAddedEvent('test me'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))

        # Test an unmatched comment, history should remain the same
        pr = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(pr.getCommentAddedEvent('casual comment'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))

    @simple_layout('layouts/push-tag-github.yaml', driver='github')
    def test_tag_event(self):
        self.executor_server.hold_jobs_in_build = True

        sha = random_sha1()
        self.fake_github.emitEvent(
            self.fake_github.getPushEvent('org/project', 'refs/tags/newtag',
                                          new_rev=sha))
        self.waitUntilSettled()

        build_params = self.builds[0].parameters
        self.assertEqual('refs/tags/newtag', build_params['ZUUL_REF'])
        self.assertEqual('00000000000000000000000000000000',
                         build_params['ZUUL_OLDREV'])
        self.assertEqual(sha, build_params['ZUUL_NEWREV'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-tag').result)

    @simple_layout('layouts/push-tag-github.yaml', driver='github')
    def test_push_event(self):
        self.executor_server.hold_jobs_in_build = True

        old_sha = random_sha1()
        new_sha = random_sha1()
        self.fake_github.emitEvent(
            self.fake_github.getPushEvent('org/project', 'refs/heads/master',
                                          old_sha, new_sha))
        self.waitUntilSettled()

        build_params = self.builds[0].parameters
        self.assertEqual('refs/heads/master', build_params['ZUUL_REF'])
        self.assertEqual(old_sha, build_params['ZUUL_OLDREV'])
        self.assertEqual(new_sha, build_params['ZUUL_NEWREV'])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        self.assertEqual('SUCCESS',
                         self.getJobFromHistory('project-post').result)

    @simple_layout('layouts/labeling-github.yaml', driver='github')
    def test_labels(self):
        A = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(A.addLabel('test'))
        self.waitUntilSettled()
        self.assertEqual(1, len(self.history))
        self.assertEqual('project-labels', self.history[0].name)
        self.assertEqual(['tests passed'], A.labels)

        # test label removed
        B = self.fake_github.openFakePullRequest('org/project', 'master')
        B.addLabel('do not test')
        self.fake_github.emitEvent(B.removeLabel('do not test'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))
        self.assertEqual('project-labels', self.history[1].name)
        self.assertEqual(['tests passed'], B.labels)

        # test unmatched label
        C = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(C.addLabel('other label'))
        self.waitUntilSettled()
        self.assertEqual(2, len(self.history))
        self.assertEqual(['other label'], C.labels)

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_git_https_url(self):
        """Test that git_ssh option gives git url with ssh"""
        url = self.fake_github.real_getGitUrl('org/project')
        self.assertEqual('https://github.com/org/project', url)

    @simple_layout('layouts/basic-github.yaml', driver='github')
    def test_git_ssh_url(self):
        """Test that git_ssh option gives git url with ssh"""
        url = self.fake_github_ssh.real_getGitUrl('org/project')
        self.assertEqual('ssh://git@github.com/org/project.git', url)

    @simple_layout('layouts/reporting-github.yaml', driver='github')
    def test_reporting(self):
        # pipeline reports pull status both on start and success
        self.executor_server.hold_jobs_in_build = True
        pr = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(pr.getPullRequestOpenedEvent())
        self.waitUntilSettled()
        self.assertIn('check', pr.statuses)
        check_status = pr.statuses['check']
        self.assertEqual('Standard check', check_status['description'])
        self.assertEqual('pending', check_status['state'])
        self.assertEqual('http://zuul.example.com/status', check_status['url'])
        self.assertEqual(0, len(pr.comments))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        check_status = pr.statuses['check']
        self.assertEqual('Standard check', check_status['description'])
        self.assertEqual('success', check_status['state'])
        self.assertEqual('http://zuul.example.com/status', check_status['url'])
        self.assertEqual(1, len(pr.comments))
        self.assertThat(pr.comments[0],
                        MatchesRegex('.*Build succeeded.*', re.DOTALL))

        # pipeline does not report any status but does comment
        self.executor_server.hold_jobs_in_build = True
        self.fake_github.emitEvent(
            pr.getCommentAddedEvent('reporting check'))
        self.waitUntilSettled()
        self.assertNotIn('reporting', pr.statuses)
        # comments increased by one for the start message
        self.assertEqual(2, len(pr.comments))
        self.assertThat(pr.comments[1],
                        MatchesRegex('.*Starting reporting jobs.*', re.DOTALL))
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        self.assertNotIn('reporting', pr.statuses)
        self.assertEqual(2, len(pr.comments))

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_report_pull_merge(self):
        # pipeline merges the pull request on success
        A = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(A.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)

        # pipeline merges the pull request on success after failure
        self.fake_github.merge_failure = True
        B = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(B.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertFalse(B.is_merged)
        self.fake_github.merge_failure = False

        # pipeline merges the pull request on second run of merge
        # first merge failed on 405 Method Not Allowed error
        self.fake_github.merge_not_allowed_count = 1
        C = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(C.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(C.is_merged)

        # pipeline does not merge the pull request
        # merge failed on 405 Method Not Allowed error - twice
        self.fake_github.merge_not_allowed_count = 2
        D = self.fake_github.openFakePullRequest('org/project', 'master')
        self.fake_github.emitEvent(D.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertFalse(D.is_merged)
