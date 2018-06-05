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
import subprocess
import tempfile
import testtools
import time
import os

from zuul.driver import bubblewrap
from zuul.executor.server import SshAgent
from tests.base import iterate_timeout


class TestBubblewrap(testtools.TestCase):
    def setUp(self):
        super(TestBubblewrap, self).setUp()
        self.log_fixture = self.useFixture(
            fixtures.FakeLogger(level=logging.DEBUG))
        self.useFixture(fixtures.NestedTempfile())

    def test_bubblewrap_wraps(self):
        bwrap = bubblewrap.BubblewrapDriver()
        context = bwrap.getExecutionContext()
        work_dir = tempfile.mkdtemp()
        ssh_agent = SshAgent()
        self.addCleanup(ssh_agent.stop)
        ssh_agent.start()
        po = context.getPopen(work_dir=work_dir,
                              ssh_auth_sock=ssh_agent.env['SSH_AUTH_SOCK'])
        self.assertTrue(po.fds[0] > 2)
        self.assertTrue(po.fds[1] > 2)
        self.assertTrue(work_dir in po.command)
        # Now run /usr/bin/id to verify passwd/group entries made it in
        true_proc = po(['/usr/bin/id'], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        (output, errs) = true_proc.communicate()
        # Make sure it printed things on stdout
        self.assertTrue(len(output.strip()))
        # And that it did not print things on stderr
        self.assertEqual(0, len(errs.strip()))
        # Make sure the _r's are closed
        self.assertEqual([], po.fds)

    def test_bubblewrap_leak(self):
        bwrap = bubblewrap.BubblewrapDriver()
        context = bwrap.getExecutionContext()
        work_dir = tempfile.mkdtemp()
        ansible_dir = tempfile.mkdtemp()
        ssh_agent = SshAgent()
        self.addCleanup(ssh_agent.stop)
        ssh_agent.start()
        po = context.getPopen(work_dir=work_dir,
                              ansible_dir=ansible_dir,
                              ssh_auth_sock=ssh_agent.env['SSH_AUTH_SOCK'])
        leak_time = 60
        # Use hexadecimal notation to avoid false-positive
        true_proc = po(['bash', '-c', 'sleep 0x%X & disown' % leak_time])
        self.assertEqual(0, true_proc.wait())
        cmdline = "sleep\x000x%X\x00" % leak_time
        for x in iterate_timeout(30, "process to exit"):
            try:
                sleep_proc = [pid for pid in os.listdir("/proc") if
                              os.path.isfile("/proc/%s/cmdline" % pid) and
                              open("/proc/%s/cmdline" % pid).read() == cmdline]
                if not sleep_proc:
                    break
            except FileNotFoundError:
                pass
            except ProcessLookupError:
                pass
            time.sleep(1)
