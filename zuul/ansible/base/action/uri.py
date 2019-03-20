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
uri = paths._import_ansible_action_plugin("uri")


class ActionModule(uri.ActionModule):

    def _find_needle(self, dirname, needle):
        return paths._safe_find_needle(
            super(ActionModule, self), dirname, needle)

    def run(self, tmp=None, task_vars=None):

        if not paths._is_official_module(self):
            return paths._fail_module_dict(self._task.action)

        if paths._is_localhost_task(self):
            for arg in ('src', 'dest'):
                dest = self._task.args.get(arg)
                if dest:
                    paths._fail_if_unsafe(dest)

        return super(ActionModule, self).run(tmp, task_vars)
