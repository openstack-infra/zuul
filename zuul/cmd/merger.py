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

import signal
import socket
import sys

import zuul.cmd
import zuul.merger.server
from zuul.lib.config import get_default

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

    def send_command(self, cmd):
        command_socket = get_default(
            self.config, 'merger', 'command_socket',
            '/var/lib/zuul/merger.socket')
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(command_socket)
        cmd = '%s\n' % cmd
        s.sendall(cmd.encode('utf8'))

    def exit_handler(self):
        self.merger.stop()
        self.merger.join()

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

        signal.signal(signal.SIGUSR2, zuul.cmd.stack_dump_handler)

        if self.args.nodaemon:
            while True:
                try:
                    signal.pause()
                except KeyboardInterrupt:
                    print("Ctrl + C: asking merger to exit nicely...\n")
                    self.exit_handler()
                    sys.exit(0)
        else:
            self.merger.join()


def main():
    Merger().main()


if __name__ == "__main__":
    main()
