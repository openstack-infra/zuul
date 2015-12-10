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


def configure_connections(config):
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

    return connections
