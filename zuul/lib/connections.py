# Copyright 2015 Rackspace Australia
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
import re

import zuul.driver.zuul
import zuul.driver.gerrit
import zuul.driver.git
import zuul.driver.github
import zuul.driver.smtp
import zuul.driver.timer
import zuul.driver.sql
from zuul.connection import BaseConnection


class DefaultConnection(BaseConnection):
    pass


class ConnectionRegistry(object):
    """A registry of connections"""

    log = logging.getLogger("zuul.ConnectionRegistry")

    def __init__(self):
        self.connections = {}
        self.drivers = {}

        self.registerDriver(zuul.driver.zuul.ZuulDriver())
        self.registerDriver(zuul.driver.gerrit.GerritDriver())
        self.registerDriver(zuul.driver.git.GitDriver())
        self.registerDriver(zuul.driver.github.GithubDriver())
        self.registerDriver(zuul.driver.smtp.SMTPDriver())
        self.registerDriver(zuul.driver.timer.TimerDriver())
        self.registerDriver(zuul.driver.sql.SQLDriver())

    def registerDriver(self, driver):
        if driver.name in self.drivers:
            raise Exception("Driver %s already registered" % driver.name)
        self.drivers[driver.name] = driver

    def registerScheduler(self, sched, load=True):
        for driver_name, driver in self.drivers.items():
            if hasattr(driver, 'registerScheduler'):
                driver.registerScheduler(sched)
        for connection_name, connection in self.connections.items():
            connection.registerScheduler(sched)
            if load:
                connection.onLoad()

    def registerWebapp(self, webapp):
        for driver_name, driver in self.drivers.items():
            if hasattr(driver, 'registerWebapp'):
                driver.registerWebapp(webapp)
        for connection_name, connection in self.connections.items():
            connection.registerWebapp(webapp)

    def reconfigureDrivers(self, tenant):
        for driver in self.drivers.values():
            if hasattr(driver, 'reconfigure'):
                driver.reconfigure(tenant)

    def stop(self):
        for connection_name, connection in self.connections.items():
            connection.onStop()
        for driver in self.drivers.values():
            driver.stop()

    def configure(self, config):
        # Register connections from the config
        connections = {}

        for section_name in config.sections():
            con_match = re.match(r'^connection ([\'\"]?)(.*)(\1)$',
                                 section_name, re.I)
            if not con_match:
                continue
            con_name = con_match.group(2)
            con_config = dict(config.items(section_name))

            if 'driver' not in con_config:
                raise Exception("No driver specified for connection %s."
                                % con_name)

            con_driver = con_config['driver']
            if con_driver not in self.drivers:
                raise Exception("Unknown driver, %s, for connection %s"
                                % (con_config['driver'], con_name))

            driver = self.drivers[con_driver]
            connection = driver.getConnection(con_name, con_config)
            connections[con_name] = connection

        # If the [gerrit] or [smtp] sections still exist, load them in as a
        # connection named 'gerrit' or 'smtp' respectfully

        if 'gerrit' in config.sections():
            if 'gerrit' in connections:
                self.log.warning(
                    "The legacy [gerrit] section will be ignored in favour"
                    " of the [connection gerrit].")
            else:
                driver = self.drivers['gerrit']
                connections['gerrit'] = \
                    driver.getConnection(
                        'gerrit', dict(config.items('gerrit')))

        if 'smtp' in config.sections():
            if 'smtp' in connections:
                self.log.warning(
                    "The legacy [smtp] section will be ignored in favour"
                    " of the [connection smtp].")
            else:
                driver = self.drivers['smtp']
                connections['smtp'] = \
                    driver.getConnection(
                        'smtp', dict(config.items('smtp')))

        # Create default connections for drivers which need no
        # connection information (e.g., 'timer' or 'zuul').
        for driver in self.drivers.values():
            if not hasattr(driver, 'getConnection'):
                connections[driver.name] = DefaultConnection(
                    driver, driver.name, {})

        self.connections = connections

    def getSource(self, connection_name):
        connection = self.connections[connection_name]
        return connection.driver.getSource(connection)

    def getReporter(self, connection_name, config=None):
        connection = self.connections[connection_name]
        return connection.driver.getReporter(connection, config)

    def getTrigger(self, connection_name, config=None):
        connection = self.connections[connection_name]
        return connection.driver.getTrigger(connection, config)
