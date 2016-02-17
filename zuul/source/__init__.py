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

import six


@six.add_metaclass(abc.ABCMeta)
class BaseSource(object):
    """Base class for sources.

    A source class gives methods for fetching and updating changes. Each
    pipeline must have (only) one source. It is the canonical provider of the
    change to be tested.

    Defines the exact public methods that must be supplied."""

    def __init__(self, source_config={}, sched=None, connection=None):
        self.source_config = source_config
        self.sched = sched
        self.connection = connection

    def stop(self):
        """Stop the source."""

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
    def getChange(self, event, project):
        """Get the change representing an event."""

    @abc.abstractmethod
    def getProjectOpenChanges(self, project):
        """Get the open changes for a project."""

    @abc.abstractmethod
    def getGitUrl(self, project):
        """Get the git url for a project."""
