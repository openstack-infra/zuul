# Copyright 2017 IBM Corp.
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

from zuul.driver import Driver, ConnectionInterface, TriggerInterface
from zuul.driver import SourceInterface
from zuul.driver.github import githubconnection
from zuul.driver.github import githubtrigger
from zuul.driver.github import githubsource
from zuul.driver.github import githubreporter


class GithubDriver(Driver, ConnectionInterface, TriggerInterface,
                   SourceInterface):
    name = 'github'

    def getConnection(self, name, config):
        return githubconnection.GithubConnection(self, name, config)

    def getTrigger(self, connection, config=None):
        return githubtrigger.GithubTrigger(self, connection, config)

    def getSource(self, connection):
        return githubsource.GithubSource(self, connection)

    def getReporter(self, connection, config=None):
        return githubreporter.GithubReporter(self, connection, config)

    def getTriggerSchema(self):
        return githubtrigger.getSchema()

    def getReporterSchema(self):
        return githubreporter.getSchema()

    def getRequireSchema(self):
        return githubsource.getRequireSchema()

    def getRejectSchema(self):
        return githubsource.getRejectSchema()
