# Copyright 2017 Red Hat, Inc.
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
from zuul.driver.mqtt import mqttconnection
from zuul.driver.mqtt import mqttreporter


class MQTTDriver(Driver, ConnectionInterface, ReporterInterface):
    name = 'mqtt'

    def getConnection(self, name, config):
        return mqttconnection.MQTTConnection(self, name, config)

    def getReporter(self, connection, pipeline, config=None):
        return mqttreporter.MQTTReporter(self, connection, config)

    def getReporterSchema(self):
        return mqttreporter.getSchema()
