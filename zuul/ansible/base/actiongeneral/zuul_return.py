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

from ansible.plugins.action import ActionBase

from zuul.ansible import paths


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


def merge_data(dict_a, dict_b):
    """
    Merge dict_a into dict_b, handling any special cases for zuul variables
    """
    artifacts_a = dict_a.get('zuul', {}).get('artifacts', [])
    if not isinstance(artifacts_a, list):
        artifacts_a = []
    artifacts_b = dict_b.get('zuul', {}).get('artifacts', [])
    if not isinstance(artifacts_b, list):
        artifacts_b = []
    artifacts = artifacts_a + artifacts_b
    merge_dict(dict_a, dict_b)
    if artifacts:
        dict_b.setdefault('zuul', {})['artifacts'] = artifacts
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
            merge_data(json.load(f), data)
    if new_data:
        merge_data(new_data, data)

    (f, tmp_path) = tempfile.mkstemp(dir=workdir)
    try:
        f = os.fdopen(f, 'w')
        json.dump(data, f)
        f.close()
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()
        results = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # tmp no longer has any effect

        path = self._task.args.get('path')
        if not path:
            path = os.path.join(os.environ['ZUUL_JOBDIR'], 'work',
                                'results.json')

        if not paths._is_safe_path(path, allow_trusted=False):
            return paths._fail_dict(path)

        set_value(
            path, self._task.args.get('data'), self._task.args.get('file'))

        return results
