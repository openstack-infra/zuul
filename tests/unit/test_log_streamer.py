#!/usr/bin/env python

# Copyright 2017 Red Hat, Inc.
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
import socket
import tempfile

import zuul.lib.log_streamer
import tests.base


class TestLogStreamer(tests.base.BaseTestCase):

    log = logging.getLogger("zuul.test.cloner")

    def setUp(self):
        super(TestLogStreamer, self).setUp()
        self.host = '0.0.0.0'

    def startStreamer(self, port, root=None):
        if not root:
            root = tempfile.gettempdir()
        return zuul.lib.log_streamer.LogStreamer(None, self.host, port, root)

    def test_start_stop(self):
        port = 7900
        streamer = self.startStreamer(port)
        self.addCleanup(streamer.stop)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(s.close)
        self.assertEqual(0, s.connect_ex((self.host, port)))
        s.close()

        streamer.stop()

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(s.close)
        self.assertNotEqual(0, s.connect_ex((self.host, port)))
        s.close()
