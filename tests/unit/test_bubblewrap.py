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
import os

from zuul.driver import bubblewrap
from zuul.executor.server import SshAgent


class TestBubblewrap(testtools.TestCase):
    def setUp(self):
        super(TestBubblewrap, self).setUp()
        self.log_fixture = self.useFixture(
            fixtures.FakeLogger(level=logging.DEBUG))
        self.useFixture(fixtures.NestedTempfile())

    def test_bubblewrap_wraps(self):
        bwrap = bubblewrap.BubblewrapDriver()
        work_dir = tempfile.mkdtemp()
        ansible_dir = tempfile.mkdtemp()
        ssh_agent = SshAgent()
        self.addCleanup(ssh_agent.stop)
        ssh_agent.start()
        po = bwrap.getPopen(work_dir=work_dir,
                            ansible_dir=ansible_dir,
                            ssh_auth_sock=ssh_agent.env['SSH_AUTH_SOCK'])
        self.assertTrue(po.passwd_r > 2)
        self.assertTrue(po.group_r > 2)
        self.assertTrue(work_dir in po.command)
        self.assertTrue(ansible_dir in po.command)
        # Now run /usr/bin/id to verify passwd/group entries made it in
        true_proc = po(['/usr/bin/id'], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        (output, errs) = true_proc.communicate()
        # Make sure it printed things on stdout
        self.assertTrue(len(output.strip()))
        # And that it did not print things on stderr
        self.assertEqual(0, len(errs.strip()))
        # Make sure the _r's are closed
        self.assertIsNone(po.passwd_r)
        self.assertIsNone(po.group_r)

    def test_bubblewrap_leak(self):
        bwrap = bubblewrap.BubblewrapDriver()
        work_dir = tempfile.mkdtemp()
        ansible_dir = tempfile.mkdtemp()
        ssh_agent = SshAgent()
        self.addCleanup(ssh_agent.stop)
        ssh_agent.start()
        po = bwrap.getPopen(work_dir=work_dir,
                            ansible_dir=ansible_dir,
                            ssh_auth_sock=ssh_agent.env['SSH_AUTH_SOCK'])
        leak_time = 7
        # Use hexadecimal notation to avoid false-positive
        true_proc = po(['bash', '-c', 'sleep 0x%X & disown' % leak_time])
        self.assertEqual(0, true_proc.wait())
        cmdline = "sleep\x000x%X\x00" % leak_time
        sleep_proc = [pid for pid in os.listdir("/proc") if
                      os.path.isfile("/proc/%s/cmdline" % pid) and
                      open("/proc/%s/cmdline" % pid).read() == cmdline]
        self.assertEqual(len(sleep_proc), 0, "Processes leaked")
