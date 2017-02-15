# Copyright 2011 OpenStack, LLC.
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
import voluptuous as v

from zuul.connection import BaseConnection
from zuul.model import Project


class GitConnection(BaseConnection):
    driver_name = 'git'
    log = logging.getLogger("connection.git")

    def __init__(self, driver, connection_name, connection_config):
        super(GitConnection, self).__init__(driver, connection_name,
                                            connection_config)
        if 'baseurl' not in self.connection_config:
            raise Exception('baseurl is required for git connections in '
                            '%s' % self.connection_name)

        self.baseurl = self.connection_config.get('baseurl')
        self.projects = {}

    def getProject(self, name):
        if name not in self.projects:
            self.projects[name] = Project(name, self.connection_name)
        return self.projects[name]

    def getProjectBranches(self, project):
        # TODO(jeblair): implement; this will need to handle local or
        # remote git urls.
        raise NotImplemented()

    def getGitUrl(self, project):
        url = '%s/%s' % (self.baseurl, project.name)
        return url


def getSchema():
    git_connection = v.Any(str, v.Schema({}, extra=True))
    return git_connection
