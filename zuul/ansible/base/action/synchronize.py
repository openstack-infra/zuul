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
synchronize = paths._import_ansible_action_plugin("synchronize")


class ActionModule(synchronize.ActionModule):

    def run(self, tmp=None, task_vars=None):
        if not paths._is_official_module(self):
            return paths._fail_module_dict(self._task.action)

        try:
            delegate_to = self._task.delegate_to
        except (AttributeError, KeyError):
            delegate_to = None

        if delegate_to and not paths._is_localhost_task(self):
            return super(ActionModule, self).run(tmp, task_vars)

        source = self._task.args.get('src', None)
        dest = self._task.args.get('dest', None)
        mode = self._task.args.get('mode', 'push')

        if 'rsync_opts' not in self._task.args:
            self._task.args['rsync_opts'] = []
        if '--safe-links' not in self._task.args['rsync_opts']:
            self._task.args['rsync_opts'].append('--safe-links')

        if mode == 'push' and not paths._is_safe_path(
                source, allow_trusted=True):
            return paths._fail_dict(source, prefix='Syncing files from')
        if mode == 'pull' and not paths._is_safe_path(dest):
            return paths._fail_dict(dest, prefix='Syncing files to')
        return super(ActionModule, self).run(tmp, task_vars)
