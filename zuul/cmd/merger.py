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

import zuul.cmd

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


class Merger(zuul.cmd.ZuulDaemonApp):
    app_name = 'merger'
    app_description = 'A standalone Zuul merger.'

    def exit_handler(self, signum, frame):
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        self.merger.stop()
        self.merger.join()

    def run(self):
        # See comment at top of file about zuul imports
        import zuul.merger.server

        self.configure_connections(source_only=True)

        self.setup_logging('merger', 'log_config')

        self.merger = zuul.merger.server.MergeServer(self.config,
                                                     self.connections)
        self.merger.start()

        signal.signal(signal.SIGUSR1, self.exit_handler)
        signal.signal(signal.SIGUSR2, zuul.cmd.stack_dump_handler)
        while True:
            try:
                signal.pause()
            except KeyboardInterrupt:
                print("Ctrl + C: asking merger to exit nicely...\n")
                self.exit_handler(signal.SIGINT, None)


def main():
    Merger().main()


if __name__ == "__main__":
    main()
