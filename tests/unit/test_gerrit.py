#!/usr/bin/env python

# Copyright 2015 BMW Car IT GmbH
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

try:
    from unittest import mock
except ImportError:
    import mock

import tests.base
from tests.base import BaseTestCase
from zuul.driver.gerrit import GerritDriver
from zuul.driver.gerrit.gerritconnection import GerritConnection

FIXTURE_DIR = os.path.join(tests.base.FIXTURE_DIR, 'gerrit')


def read_fixture(file):
    with open('%s/%s' % (FIXTURE_DIR, file), 'r') as fixturefile:
        lines = fixturefile.readlines()
        command = lines[0].replace('\n', '')
        value = ''.join(lines[1:])
        return command, value


def read_fixtures(files):
    calls = []
    values = []
    for fixture_file in files:
        command, value = read_fixture(fixture_file)
        calls.append(mock.call(command))
        values.append([value, ''])
    return calls, values


class TestGerrit(BaseTestCase):

    @mock.patch('zuul.driver.gerrit.gerritconnection.GerritConnection._ssh')
    def run_query(self, files, expected_patches, _ssh_mock):
        gerrit_config = {
            'user': 'gerrit',
            'server': 'localhost',
        }
        driver = GerritDriver()
        gerrit = GerritConnection(driver, 'review_gerrit', gerrit_config)

        calls, values = read_fixtures(files)
        _ssh_mock.side_effect = values

        result = gerrit.simpleQuery('project:openstack-infra/zuul')

        _ssh_mock.assert_has_calls(calls)
        self.assertEqual(len(calls), _ssh_mock.call_count,
                         '_ssh should be called %d times' % len(calls))
        self.assertIsNotNone(result, 'Result is not none')
        self.assertEqual(len(result), expected_patches,
                         'There must be %d patches.' % expected_patches)

    def test_simple_query_pagination_new(self):
        files = ['simple_query_pagination_new_1',
                 'simple_query_pagination_new_2']
        expected_patches = 5
        self.run_query(files, expected_patches)

    def test_simple_query_pagination_old(self):
        files = ['simple_query_pagination_old_1',
                 'simple_query_pagination_old_2',
                 'simple_query_pagination_old_3']
        expected_patches = 5
        self.run_query(files, expected_patches)
