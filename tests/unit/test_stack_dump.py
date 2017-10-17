# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import fixtures
import logging
import signal
import testtools

import zuul.cmd


class TestStackDump(testtools.TestCase):
    def setUp(self):
        super(TestStackDump, self).setUp()
        self.log_fixture = self.useFixture(
            fixtures.FakeLogger(level=logging.DEBUG))

    def test_stack_dump_logs(self):
        "Test that stack dumps end up in logs."

        zuul.cmd.stack_dump_handler(signal.SIGUSR2, None)
        self.assertIn("Thread", self.log_fixture.output)
        self.assertIn("MainThread", self.log_fixture.output)
        self.assertIn("test_stack_dump_logs", self.log_fixture.output)
