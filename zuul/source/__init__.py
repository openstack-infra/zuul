# Copyright 2014 Rackspace Australia
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

import abc


class BaseSource(object, metaclass=abc.ABCMeta):
    """Base class for sources.

    A source class gives methods for fetching and updating changes. Each
    pipeline must have (only) one source. It is the canonical provider of the
    change to be tested.

    Defines the exact public methods that must be supplied."""

    def __init__(self, driver, connection, canonical_hostname, config=None):
        self.driver = driver
        self.connection = connection
        self.canonical_hostname = canonical_hostname
        self.config = config or {}

    @abc.abstractmethod
    def getRefSha(self, project, ref):
        """Return a sha for a given project ref."""

    @abc.abstractmethod
    def isMerged(self, change, head=None):
        """Determine if change is merged.

        If head is provided the change is checked if it is at head."""

    @abc.abstractmethod
    def canMerge(self, change, allow_needs):
        """Determine if change can merge."""

    def postConfig(self):
        """Called after configuration has been processed."""

    @abc.abstractmethod
    def getChange(self, event):
        """Get the change representing an event."""

    @abc.abstractmethod
    def getChangeByURL(self, url):
        """Get the change corresponding to the supplied URL.

        The URL may may not correspond to this source; if it doesn't,
        or there is no change at that URL, return None.

        """

    @abc.abstractmethod
    def getChangesDependingOn(self, change, projects, tenant):
        """Return changes which depend on changes at the supplied URIs.

        Search this source for changes which depend on the supplied
        change.  Generally the Change.uris attribute should be used to
        perform the search, as it contains a list of URLs without the
        scheme which represent a single change

        If the projects argument is None, search across all known
        projects.  If it is supplied, the search may optionally be
        restricted to only those projects.

        The tenant argument can be used by the source to limit the
        search scope.
        """

    @abc.abstractmethod
    def getProjectOpenChanges(self, project):
        """Get the open changes for a project."""

    @abc.abstractmethod
    def getGitUrl(self, project):
        """Get the git url for a project."""

    @abc.abstractmethod
    def getProject(self, name):
        """Get a project."""

    @abc.abstractmethod
    def getProjectBranches(self, project, tenant):
        """Get branches for a project"""

    @abc.abstractmethod
    def getRequireFilters(self, config):
        """Return a list of ChangeFilters for the scheduler to match against.
        """

    @abc.abstractmethod
    def getRejectFilters(self, config):
        """Return a list of ChangeFilters for the scheduler to match against.
        """
