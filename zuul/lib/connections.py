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

import re

import zuul.connection.gerrit
import zuul.connection.smtp


class ConnectionRegistry(object):
    """A registry of connections"""

    def __init__(self):
        self.connections = {}

    def registerScheduler(self, sched):
        for connection_name, connection in self.connections.items():
            connection.registerScheduler(sched)
            connection.onLoad()

    def stop(self):
        for connection_name, connection in self.connections.items():
            connection.onStop()

    def configure(self, config):
        # Register connections from the config
        # TODO(jhesketh): import connection modules dynamically
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

            # TODO(jhesketh): load the required class automatically
            if con_driver == 'gerrit':
                connections[con_name] = \
                    zuul.connection.gerrit.GerritConnection(con_name,
                                                            con_config)
            elif con_driver == 'smtp':
                connections[con_name] = \
                    zuul.connection.smtp.SMTPConnection(con_name, con_config)
            else:
                raise Exception("Unknown driver, %s, for connection %s"
                                % (con_config['driver'], con_name))

        # If the [gerrit] or [smtp] sections still exist, load them in as a
        # connection named 'gerrit' or 'smtp' respectfully

        if 'gerrit' in config.sections():
            connections['gerrit'] = \
                zuul.connection.gerrit.GerritConnection(
                    'gerrit', dict(config.items('gerrit')))

        if 'smtp' in config.sections():
            connections['smtp'] = \
                zuul.connection.smtp.SMTPConnection(
                    'smtp', dict(config.items('smtp')))

        self.connections = connections

    def _getDriver(self, dtype, connection_name, driver_config={}):
        # Instantiate a driver such as a trigger, source or reporter
        # TODO(jhesketh): Make this list dynamic or use entrypoints etc.
        # Stevedore was not a good fit here due to the nature of triggers.
        # Specifically we don't want to load a trigger per a pipeline as one
        # trigger can listen to a stream (from gerrit, for example) and the
        # scheduler decides which eventfilter to use. As such we want to load
        # trigger+connection pairs uniquely.
        drivers = {
            'source': {
                'gerrit': 'zuul.source.gerrit:GerritSource',
            },
            'trigger': {
                'gerrit': 'zuul.trigger.gerrit:GerritTrigger',
                'timer': 'zuul.trigger.timer:TimerTrigger',
                'zuul': 'zuul.trigger.zuultrigger:ZuulTrigger',
            },
            'reporter': {
                'gerrit': 'zuul.reporter.gerrit:GerritReporter',
                'smtp': 'zuul.reporter.smtp:SMTPReporter',
            },
        }

        # TODO(jhesketh): Check the connection_name exists
        if connection_name in self.connections.keys():
            driver_name = self.connections[connection_name].driver_name
            connection = self.connections[connection_name]
        else:
            # In some cases a driver may not be related to a connection. For
            # example, the 'timer' or 'zuul' triggers.
            driver_name = connection_name
            connection = None
        driver = drivers[dtype][driver_name].split(':')
        driver_instance = getattr(
            __import__(driver[0], fromlist=['']), driver[1])(
                driver_config, connection
        )

        return driver_instance

    def getSource(self, connection_name):
        return self._getDriver('source', connection_name)

    def getReporter(self, connection_name, driver_config={}):
        return self._getDriver('reporter', connection_name, driver_config)

    def getTrigger(self, connection_name, driver_config={}):
        return self._getDriver('trigger', connection_name, driver_config)
