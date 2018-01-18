# Copyright 2014 Antoine "hashar" Musso
# Copyright 2014 Wikimedia Foundation Inc.
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

from collections import defaultdict
from collections import OrderedDict
import logging
import os
import re


class CloneMapper(object):
    log = logging.getLogger("zuul.CloneMapper")

    def __init__(self, clonemap, projects):
        self.clonemap = clonemap
        self.projects = projects

    def expand(self, workspace):
        self.log.info("Workspace path set to: %s", workspace)

        is_valid = True
        ret = OrderedDict()
        for project in self.projects:
            dests = []
            for mapping in self.clonemap:
                if re.match(r'^%s$' % mapping['name'],
                            project):
                    # Might be matched more than one time
                    dests.append(
                        re.sub(mapping['name'], mapping['dest'], project))

            if len(dests) > 1:
                self.log.error("Duplicate destinations for %s: %s.",
                               project, dests)
                is_valid = False
            elif len(dests) == 0:
                self.log.debug("Using %s as destination (unmatched)",
                               project)
                ret[project] = [project]
            else:
                ret[project] = dests

        if not is_valid:
            raise Exception("Expansion error. Check error messages above")

        self.log.info("Mapping projects to workspace...")
        for project, dest in ret.items():
            dest = os.path.normpath(os.path.join(workspace, dest[0]))
            ret[project] = dest
            self.log.info("  %s -> %s", project, dest)

        self.log.debug("Checking overlap in destination directories...")
        check = defaultdict(list)
        for project, dest in ret.items():
            check[dest].append(project)

        dupes = dict((d, p) for (d, p) in check.items() if len(p) > 1)
        if dupes:
            raise Exception("Some projects share the same destination: %s",
                            dupes)

        self.log.info("Expansion completed.")
        return ret
