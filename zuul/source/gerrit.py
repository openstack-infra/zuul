# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import logging
from zuul.source import BaseSource


class GerritSource(BaseSource):
    name = 'gerrit'
    log = logging.getLogger("zuul.source.Gerrit")

    def getRefSha(self, project, ref):
        return self.connection.getRefSha(project, ref)

    def isMerged(self, change, head=None):
        return self.connection.isMerged(change, head)

    def canMerge(self, change, allow_needs):
        return self.connection.canMerge(change, allow_needs)

    def postConfig(self):
        pass

    def getChange(self, event):
        return self.connection.getChange(event)

    def getProject(self, name):
        return self.connection.getProject(name)

    def getProjectOpenChanges(self, project):
        return self.connection.getProjectOpenChanges(project)

    def getGitUrl(self, project):
        return self.connection.getGitUrl(project)

    def _getGitwebUrl(self, project, sha=None):
        return self.connection.getGitwebUrl(project, sha)
