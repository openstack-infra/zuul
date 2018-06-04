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

from zuul.driver import Driver, ConnectionInterface, TriggerInterface
from zuul.driver import SourceInterface, ReporterInterface
from zuul.driver.gerrit import gerritconnection
from zuul.driver.gerrit import gerrittrigger
from zuul.driver.gerrit import gerritsource
from zuul.driver.gerrit import gerritreporter


class GerritDriver(Driver, ConnectionInterface, TriggerInterface,
                   SourceInterface, ReporterInterface):
    name = 'gerrit'

    def getConnection(self, name, config):
        return gerritconnection.GerritConnection(self, name, config)

    def getTrigger(self, connection, config=None):
        return gerrittrigger.GerritTrigger(self, connection, config)

    def getSource(self, connection):
        return gerritsource.GerritSource(self, connection)

    def getReporter(self, connection, pipeline, config=None):
        return gerritreporter.GerritReporter(self, connection, config)

    def getTriggerSchema(self):
        return gerrittrigger.getSchema()

    def getReporterSchema(self):
        return gerritreporter.getSchema()

    def getRequireSchema(self):
        return gerritsource.getRequireSchema()

    def getRejectSchema(self):
        return gerritsource.getRejectSchema()
