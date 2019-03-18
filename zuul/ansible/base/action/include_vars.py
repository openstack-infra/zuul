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
include_vars = paths._import_ansible_action_plugin("include_vars")


class ActionModule(include_vars.ActionModule):

    def _find_needle(self, dirname, needle):
        return paths._safe_find_needle(
            super(ActionModule, self), dirname, needle)

    def run(self, tmp=None, task_vars=None):
        if not paths._is_official_module(self):
            return paths._fail_module_dict(self._task.action)

        source_dir = self._task.args.get('dir', None)

        # This is the handling for source_dir. The source_file is handled by
        # the _find_needle override.
        if source_dir:
            self._set_args()
            self._set_root_dir()
            if not paths._is_safe_path(self.source_dir, allow_trusted=True):
                return paths._fail_dict(self.source_dir)
        return super(ActionModule, self).run(tmp, task_vars)
