#!/usr/bin/env python

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

import testtools
import zuul.cmd.cloner


class TestClonerCmdArguments(testtools.TestCase):

    def setUp(self):
        super(TestClonerCmdArguments, self).setUp()
        self.app = zuul.cmd.cloner.Cloner()

    def test_default_cache_dir_empty(self):
        self.app.parse_arguments(['base', 'repo'])
        self.assertIsNone(self.app.args.cache_dir)

    def test_default_cache_dir_environ(self):
        try:
            os.environ['ZUUL_CACHE_DIR'] = 'fromenviron'
            self.app.parse_arguments(['base', 'repo'])
            self.assertEqual('fromenviron', self.app.args.cache_dir)
        finally:
            del os.environ['ZUUL_CACHE_DIR']

    def test_default_cache_dir_override_environ(self):
        try:
            os.environ['ZUUL_CACHE_DIR'] = 'fromenviron'
            self.app.parse_arguments(['--cache-dir', 'argument',
                                      'base', 'repo'])
            self.assertEqual('argument', self.app.args.cache_dir)
        finally:
            del os.environ['ZUUL_CACHE_DIR']

    def test_default_cache_dir_argument(self):
        self.app.parse_arguments(['--cache-dir', 'argument',
                                  'base', 'repo'])
        self.assertEqual('argument', self.app.args.cache_dir)
