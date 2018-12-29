# Copyright 2018 EasyStack, Inc.
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

import configparser

from tests.base import BaseTestCase
from tests.base import FIXTURE_DIR
from zuul.lib.config import get_default


class TestDefaultConfigValue(BaseTestCase):
    config_file = 'zuul.conf'

    def setUp(self):
        super(TestDefaultConfigValue, self).setUp()
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join(FIXTURE_DIR, self.config_file))

    def test_default_config_value(self):
        default_value = get_default(self.config,
                                    'web',
                                    'static_cache_expiry',
                                    default=3600)
        self.assertEqual(1200, default_value)
