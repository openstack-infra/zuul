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

import os

from zuul.ansible import paths
filetree = paths._import_ansible_lookup_plugin("filetree")


class LookupModule(filetree.LookupModule):

    def run(self, terms, variables=None, **kwargs):
        basedir = self.get_basedir(variables)
        for term in terms:
            term_file = os.path.basename(term)
            dwimmed_path = self._loader.path_dwim_relative(
                basedir, 'files', os.path.dirname(term))
            path = os.path.join(dwimmed_path, term_file)
            paths._fail_if_unsafe(path, allow_trusted=True)
        return super(LookupModule, self).run(terms, variables, **kwargs)
