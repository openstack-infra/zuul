# Copyright 2018 Red Hat, Inc.
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

from zuul.ansible import paths
add_host = paths._import_ansible_action_plugin("add_host")


class ActionModule(add_host.ActionModule):

    def run(self, tmp=None, task_vars=None):
        safe_args = set((
            'ansible_connection',
            'ansible_python_interpreter',
            'ansible_host',
            'ansible_port',
            'ansible_user',
            'ansible_password',
            'ansible_ssh_host',
            'ansible_ssh_port',
            'ansible_ssh_user',
            'ansible_ssh_pass',
        ))
        args = set(filter(
            lambda x: x.startswith('ansible_'), self._task.args.keys()))
        conn = self._task.args.get('ansible_connection', 'ssh')
        if args.issubset(safe_args) and conn in ('kubectl', 'ssh'):
            return super(ActionModule, self).run(tmp, task_vars)

        return dict(
            failed=True,
            msg="Adding hosts %s with %s to the inventory is prohibited" % (
                conn, " ".join(args.difference(safe_args))))
