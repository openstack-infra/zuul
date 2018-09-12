#!/usr/bin/python

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

import os
import json
import tempfile


def merge_dict(dict_a, dict_b):
    """
    Add dict_a into dict_b
    Merge values if possible else dict_a value replace dict_b value
    """
    for key in dict_a:
        if key in dict_b:
            if isinstance(dict_a[key], dict) and isinstance(dict_b[key], dict):
                merge_dict(dict_a[key], dict_b[key])
            else:
                dict_b[key] = dict_a[key]
        else:
            dict_b[key] = dict_a[key]
    return dict_b


def set_value(path, new_data, new_file):
    workdir = os.path.dirname(path)
    data = None
    if os.path.exists(path):
        with open(path, 'r') as f:
            data = f.read()
    if data:
        data = json.loads(data)
    else:
        data = {}

    if new_file:
        with open(new_file, 'r') as f:
            merge_dict(json.load(f), data)
    if new_data:
        merge_dict(new_data, data)

    (f, tmp_path) = tempfile.mkstemp(dir=workdir)
    try:
        f = os.fdopen(f, 'w')
        json.dump(data, f)
        f.close()
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(required=False, type='str'),
            data=dict(required=False, type='dict'),
            file=dict(required=False, type='str'),
        )
    )

    p = module.params
    path = p['path']
    if not path:
        path = os.path.join(os.environ['ZUUL_JOBDIR'], 'work',
                            'results.json')
    set_value(path, p['data'], p['file'])
    module.exit_json(changed=True, e=os.environ.copy())

from ansible.module_utils.basic import *  # noqa
from ansible.module_utils.basic import AnsibleModule

if __name__ == '__main__':
    main()
