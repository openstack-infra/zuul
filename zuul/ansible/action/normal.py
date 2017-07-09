# Copyright 2016 Red Hat, Inc.
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
normal = paths._import_ansible_action_plugin('normal')


class ActionModule(normal.ActionModule):

    def run(self, tmp=None, task_vars=None):

        if (self._play_context.connection == 'local'
                or self._play_context.remote_addr == 'localhost'
                or self._play_context.remote_addr.startswith('127.')
                or self._task.delegate_to == 'localhost'
                or (self._task.delegate_to
                    and self._task.delegate_to.startswtih('127.'))):
            if self._task.action == 'stat':
                paths._fail_if_unsafe(self._task.args['path'])
            elif self._task.action == 'file':
                dest = self._task.args.get(
                    'path', self._task.args.get(
                        'dest', self._task.args.get(
                            'name')))
                paths._fail_if_unsafe(dest)
            else:
                return dict(
                    failed=True,
                    msg="Executing local code is prohibited")
        return super(ActionModule, self).run(tmp, task_vars)
