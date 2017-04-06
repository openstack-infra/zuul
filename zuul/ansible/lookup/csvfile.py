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

import csv

from ansible.errors import AnsibleError
from ansible.module_utils._text import to_native

from zuul.ansible import paths
csvfile = paths._import_ansible_lookup_plugin("csvfile")


class LookupModule(csvfile.LookupModule):

    def read_csv(
            self, filename, key, delimiter, encoding='utf-8',
            dflt=None, col=1):
        paths._fail_if_unsafe(filename)

        # upstream csvfile read_csv does not work with python3 so
        # carry our own version.
        try:
            f = open(filename, 'r')
            creader = csv.reader(f, dialect=csv.excel, delimiter=delimiter)

            for row in creader:
                if row[0] == key:
                    return row[int(col)]
        except Exception as e:
            raise AnsibleError("csvfile: %s" % to_native(e))

        return dflt
