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
from zuul.model import Project


class GitSource(BaseSource):
    name = 'git'
    log = logging.getLogger("zuul.source.Git")

    def __init__(self, driver, connection, config=None):
        hostname = connection.canonical_hostname
        super(GitSource, self).__init__(driver, connection,
                                        hostname, config)

    def getRefSha(self, project, ref):
        raise NotImplemented()

    def isMerged(self, change, head=None):
        raise NotImplemented()

    def canMerge(self, change, allow_needs):
        raise NotImplemented()

    def getChange(self, event, refresh=False):
        return self.connection.getChange(event, refresh)

    def getChangeByURL(self, url):
        return None

    def getChangesDependingOn(self, change, projects):
        return []

    def getCachedChanges(self):
        return []

    def getProject(self, name):
        p = self.connection.getProject(name)
        if not p:
            p = Project(name, self)
            self.connection.addProject(p)
        return p

    def getProjectBranches(self, project, tenant):
        return self.connection.getProjectBranches(project, tenant)

    def getGitUrl(self, project):
        return self.connection.getGitUrl(project)

    def getProjectOpenChanges(self, project):
        raise NotImplemented()

    def getRequireFilters(self, config):
        return []

    def getRejectFilters(self, config):
        return []
