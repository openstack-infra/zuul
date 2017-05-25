# Copyright 2014 Puppet Labs Inc
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
import time

from zuul.source import BaseSource
from zuul.model import Project
from zuul.driver.github.githubmodel import GithubRefFilter
from zuul.driver.util import scalar_or_list, to_list


class GithubSource(BaseSource):
    name = 'github'
    log = logging.getLogger("zuul.source.GithubSource")

    def __init__(self, driver, connection, config=None):
        hostname = connection.canonical_hostname
        super(GithubSource, self).__init__(driver, connection,
                                           hostname, config)

    def getRefSha(self, project, ref):
        """Return a sha for a given project ref."""
        raise NotImplementedError()

    def waitForRefSha(self, project, ref, old_sha=''):
        """Block until a ref shows up in a given project."""
        raise NotImplementedError()

    def isMerged(self, change, head=None):
        """Determine if change is merged."""
        if not change.number:
            # Not a pull request, considering merged.
            return True
        return change.is_merged

    def canMerge(self, change, allow_needs):
        """Determine if change can merge."""

        if not change.number:
            # Not a pull request, considering merged.
            return True
        return self.connection.canMerge(change, allow_needs)

    def postConfig(self):
        """Called after configuration has been processed."""
        pass

    def getChange(self, event):
        return self.connection.getChange(event)

    def getProject(self, name):
        p = self.connection.getProject(name)
        if not p:
            p = Project(name, self)
            self.connection.addProject(p)
        return p

    def getProjectBranches(self, project):
        return self.connection.getProjectBranches(project)

    def getProjectOpenChanges(self, project):
        """Get the open changes for a project."""
        raise NotImplementedError()

    def updateChange(self, change, history=None):
        """Update information for a change."""
        raise NotImplementedError()

    def getGitUrl(self, project):
        """Get the git url for a project."""
        return self.connection.getGitUrl(project)

    def getGitwebUrl(self, project, sha=None):
        """Get the git-web url for a project."""
        return self.connection.getGitwebUrl(project, sha)

    def getPullFiles(self, project, number):
        """Get filenames of the pull request"""
        return self.connection.getPullFileNames(project, number)

    def _ghTimestampToDate(self, timestamp):
        return time.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')

    def getRequireFilters(self, config):
        f = GithubRefFilter(
            statuses=to_list(config.get('status')),
        )
        return [f]

    def getRejectFilters(self, config):
        return []


def getRequireSchema():
    require = {'status': scalar_or_list(str)}
    return require


def getRejectSchema():
    return {}
