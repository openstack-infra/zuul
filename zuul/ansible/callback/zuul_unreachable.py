# Copyright 2018 BMW Carit GmbH
#
# Zuul is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Zuul is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

# This is not needed in python3 - but it is needed in python2 because there
# is a json module in ansible.plugins.callback and python2 gets confused.
# Easy local testing with ansible-playbook is handy when hacking on zuul_stream
# so just put in the __future__ statement.
from __future__ import absolute_import

import os

from ansible.plugins.callback import default


class CallbackModule(default.CallbackModule):

    CALLBACK_VERSION = 2.0
    # aggregate means we can be loaded and not be the stdout plugin
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'zuul_unreachable'

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.output_path = os.path.join(
            os.environ['ZUUL_JOBDIR'], '.ansible', 'nodes.unreachable')
        self.unreachable_hosts = set()

    def v2_runner_on_unreachable(self, result):
        host = result._host.get_name()
        if host not in self.unreachable_hosts:
            self.unreachable_hosts.add(host)
            with open(self.output_path, 'a') as f:
                f.write('%s\n' % host)
