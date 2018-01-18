# Copyright 2017 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# Utility methods to promote consistent configuration among drivers.

import voluptuous as vs


def time_to_seconds(s):
    if s.endswith('s'):
        return int(s[:-1])
    if s.endswith('m'):
        return int(s[:-1]) * 60
    if s.endswith('h'):
        return int(s[:-1]) * 60 * 60
    if s.endswith('d'):
        return int(s[:-1]) * 24 * 60 * 60
    if s.endswith('w'):
        return int(s[:-1]) * 7 * 24 * 60 * 60
    raise Exception("Unable to parse time value: %s" % s)


def scalar_or_list(x):
    return vs.Any([x], x)


def to_list(item):
    if not item:
        return []
    if isinstance(item, list):
        return item
    return [item]
