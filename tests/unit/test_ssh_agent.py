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
import subprocess

from tests.base import ZuulTestCase
from zuul.executor.server import SshAgent


class TestSshAgent(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_ssh_agent(self):
        # Need a private key to add
        env_copy = dict(os.environ)
        # DISPLAY and SSH_ASKPASS will cause interactive test runners to get a
        # surprise
        if 'DISPLAY' in env_copy:
            del env_copy['DISPLAY']
        if 'SSH_ASKPASS' in env_copy:
            del env_copy['SSH_ASKPASS']

        agent = SshAgent()
        agent.start()
        env_copy.update(agent.env)

        pub_key_file = '{}.pub'.format(self.private_key_file)
        pub_key = None
        with open(pub_key_file) as pub_key_f:
            pub_key = pub_key_f.read().split('== ')[0]

        agent.add(self.private_key_file)
        keys = agent.list()
        self.assertEqual(1, len(keys))
        self.assertEqual(keys[0].split('== ')[0], pub_key)
        agent.remove(self.private_key_file)
        keys = agent.list()
        self.assertEqual([], keys)
        agent.stop()
        # Agent is now dead and thus this should fail
        with open('/dev/null') as devnull:
            self.assertRaises(subprocess.CalledProcessError,
                              subprocess.check_call,
                              ['ssh-add', self.private_key_file],
                              env=env_copy,
                              stderr=devnull)
