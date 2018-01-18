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

from zuul.driver import Driver, ConnectionInterface, ReporterInterface
from zuul.driver.sql import sqlconnection
from zuul.driver.sql import sqlreporter


class SQLDriver(Driver, ConnectionInterface, ReporterInterface):
    name = 'sql'

    def registerScheduler(self, scheduler):
        self.sched = scheduler

    def getConnection(self, name, config):
        return sqlconnection.SQLConnection(self, name, config)

    def getReporter(self, connection, config=None):
        return sqlreporter.SQLReporter(self, connection, config)

    def getReporterSchema(self):
        return sqlreporter.getSchema()
