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

    def run(self, tmp=None, task_vars=None):
        if not paths._is_official_module(self):
            return paths._fail_module_dict(self._task.action)

        source_dir = self._task.args.get('dir', None)
        source_file = self._task.args.get('file', None)

        for fileloc in (source_dir, source_file):
            if fileloc and not paths._is_safe_path(fileloc):
                return paths._fail_dict(fileloc)
        return super(ActionModule, self).run(tmp, task_vars)
