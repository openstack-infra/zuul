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

import os

from tests.base import AnsibleZuulTestCase


class TestOpenStack(AnsibleZuulTestCase):
    # A temporary class to experiment with how openstack can use
    # Zuulv3

    tenant_config_file = 'config/openstack/main.yaml'

    def test_nova_master(self):
        A = self.fake_gerrit.addFakeChange('openstack/nova', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('python27').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('python35').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertEqual(self.getJobFromHistory('python27').node,
                         'ubuntu-xenial')

    def test_nova_mitaka(self):
        self.create_branch('openstack/nova', 'stable/mitaka')
        A = self.fake_gerrit.addFakeChange('openstack/nova',
                                           'stable/mitaka', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('python27').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('python35').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2,
                         "A should report start and success")
        self.assertEqual(self.getJobFromHistory('python27').node,
                         'ubuntu-trusty')

    def test_dsvm_keystone_repo(self):
        self.executor_server.keep_jobdir = True
        A = self.fake_gerrit.addFakeChange('openstack/nova', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='dsvm', result='SUCCESS', changes='1,1')])
        build = self.getJobFromHistory('dsvm')

        # Check that a change to nova triggered a keystone clone
        executor_git_dir = os.path.join(self.executor_src_root,
                                        'review.example.com',
                                        'openstack', 'keystone', '.git')
        self.assertTrue(os.path.exists(executor_git_dir),
                        msg='openstack/keystone should be cloned.')

        jobdir_git_dir = os.path.join(build.jobdir.src_root,
                                      'review.example.com',
                                      'openstack', 'keystone', '.git')
        self.assertTrue(os.path.exists(jobdir_git_dir),
                        msg='openstack/keystone should be cloned.')

    def test_dsvm_nova_repo(self):
        self.executor_server.keep_jobdir = True
        A = self.fake_gerrit.addFakeChange('openstack/keystone', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertHistory([
            dict(name='dsvm', result='SUCCESS', changes='1,1')])
        build = self.getJobFromHistory('dsvm')

        # Check that a change to keystone triggered a nova clone
        executor_git_dir = os.path.join(self.executor_src_root,
                                        'review.example.com',
                                        'openstack', 'nova', '.git')
        self.assertTrue(os.path.exists(executor_git_dir),
                        msg='openstack/nova should be cloned.')

        jobdir_git_dir = os.path.join(build.jobdir.src_root,
                                      'review.example.com',
                                      'openstack', 'nova', '.git')
        self.assertTrue(os.path.exists(jobdir_git_dir),
                        msg='openstack/nova should be cloned.')
