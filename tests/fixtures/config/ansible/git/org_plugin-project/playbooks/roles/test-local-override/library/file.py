# Copyright (c) 2017 Red Hat
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

# This file, by existing, should be found instead of ansible's built in
# file module.


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(required=False, type='str'),
            state=dict(required=False, type='dict'),
        )
    )

    module.exit_json(changed=False)

from ansible.module_utils.basic import *  # noqa
from ansible.module_utils.basic import AnsibleModule
