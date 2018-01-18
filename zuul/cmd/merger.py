#!/usr/bin/env python
# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013-2014 OpenStack Foundation
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

import sys

import zuul.cmd
import zuul.merger.server

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


class Merger(zuul.cmd.ZuulDaemonApp):
    app_name = 'merger'
    app_description = 'A standalone Zuul merger.'

    def createParser(self):
        parser = super(Merger, self).createParser()
        parser.add_argument('command',
                            choices=zuul.merger.server.COMMANDS,
                            nargs='?')
        return parser

    def parseArguments(self, args=None):
        super(Merger, self).parseArguments()
        if self.args.command:
            self.args.nodaemon = True

    def exit_handler(self, signum, frame):
        self.merger.stop()

    def run(self):
        # See comment at top of file about zuul imports
        import zuul.merger.server
        if self.args.command in zuul.merger.server.COMMANDS:
            self.send_command(self.args.command)
            sys.exit(0)

        self.configure_connections(source_only=True)

        self.setup_logging('merger', 'log_config')

        self.merger = zuul.merger.server.MergeServer(self.config,
                                                     self.connections)
        self.merger.start()

        self.merger.join()


def main():
    Merger().main()


if __name__ == "__main__":
    main()
