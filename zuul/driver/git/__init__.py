# Copyright 2016 Red Hat, Inc.
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

from zuul.driver import Driver, ConnectionInterface, SourceInterface
from zuul.driver.git import gitconnection
from zuul.driver.git import gitsource
from zuul.driver.git import gittrigger


class GitDriver(Driver, ConnectionInterface, SourceInterface):
    name = 'git'

    def getConnection(self, name, config):
        return gitconnection.GitConnection(self, name, config)

    def getTrigger(self, connection, config=None):
        return gittrigger.GitTrigger(self, connection, config)

    def getSource(self, connection):
        return gitsource.GitSource(self, connection)

    def getTriggerSchema(self):
        return gittrigger.getSchema()

    def getRequireSchema(self):
        return {}

    def getRejectSchema(self):
        return {}
