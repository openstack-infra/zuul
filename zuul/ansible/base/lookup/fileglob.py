# (c) 2012, Michael DeHaan <michael.dehaan@gmail.com>
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

# Forked from lib/ansible/plugins/lookup/fileglob.py in ansible

import os
import glob

from zuul.ansible import paths

from ansible.plugins.lookup import LookupBase
from ansible.module_utils._text import to_bytes, to_text


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):

        ret = []
        for term in terms:
            term_file = os.path.basename(term)
            dwimmed_path = self.find_file_in_search_path(
                variables, 'files', os.path.dirname(term))
            if dwimmed_path:
                paths._fail_if_unsafe(dwimmed_path, allow_trusted=True)
                globbed = glob.glob(to_bytes(
                    os.path.join(dwimmed_path, term_file),
                    errors='surrogate_or_strict'))
                ret.extend(
                    to_text(g, errors='surrogate_or_strict')
                    for g in globbed if os.path.isfile(g))
        return ret
