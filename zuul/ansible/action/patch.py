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
patch = paths._import_ansible_action_plugin("patch")


class ActionModule(patch.ActionModule):

    def _find_needle(self, dirname, needle):
        return paths._safe_find_needle(
            super(ActionModule, self), dirname, needle)

    def run(self, tmp=None, task_vars=None):
        if not paths._is_official_module(self):
            return paths._fail_module_dict(self._task.action)

        if paths._is_localhost_task(self):
            # The patch module has two possibilities of describing where to
            # operate, basedir and dest. We need to perform the safe path check
            # for both.
            dirs_to_check = [
                self._task.args.get('basedir'),
                self._task.args.get('dest'),
            ]

            for directory in dirs_to_check:
                if directory is not None:
                    paths._fail_if_unsafe(directory)

        return super(ActionModule, self).run(tmp, task_vars)
