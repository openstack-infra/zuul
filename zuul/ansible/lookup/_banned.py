# Copyright 2017 Red Hat, Inc.
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

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):

    def run(self, *args, **kwargs):
        raise AnsibleError(
            "Use of lookup modules that perform local actions on the executor"
            " is forbidden.")
