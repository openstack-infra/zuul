#!/usr/bin/env python

# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import daemon
import logging
import os
import sys

import extras
import fixtures
import testtools

from tests.base import iterate_timeout

# as of python-daemon 1.6 it doesn't bundle pidlockfile anymore
# instead it depends on lockfile-0.9.1 which uses pidfile.
pid_file_module = extras.try_imports(['daemon.pidlockfile', 'daemon.pidfile'])


def daemon_test(pidfile, flagfile):
    pid = pid_file_module.TimeoutPIDLockFile(pidfile, 10)
    with daemon.DaemonContext(pidfile=pid):
        for x in iterate_timeout(30, "flagfile to be removed"):
            if not os.path.exists(flagfile):
                break
    sys.exit(0)


class TestDaemon(testtools.TestCase):
    log = logging.getLogger("zuul.test.daemon")

    def setUp(self):
        super(TestDaemon, self).setUp()
        self.test_root = self.useFixture(fixtures.TempDir(
            rootdir=os.environ.get("ZUUL_TEST_ROOT"))).path

    def test_daemon(self):
        pidfile = os.path.join(self.test_root, "daemon.pid")
        flagfile = os.path.join(self.test_root, "daemon.flag")
        open(flagfile, 'w').close()
        if not os.fork():
            self._cleanups = []
            daemon_test(pidfile, flagfile)
        for x in iterate_timeout(30, "daemon to start"):
            if os.path.exists(pidfile):
                break
        os.unlink(flagfile)
        for x in iterate_timeout(30, "daemon to stop"):
            if not os.path.exists(pidfile):
                break
