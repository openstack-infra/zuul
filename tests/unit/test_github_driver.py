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
