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

import argparse
import daemon
import extras

# as of python-daemon 1.6 it doesn't bundle pidlockfile anymore
# instead it depends on lockfile-0.9.1 which uses pidfile.
pid_file_module = extras.try_imports(['daemon.pidlockfile', 'daemon.pidfile'])

import os
import sys
import signal

import zuul.cmd

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


class Merger(zuul.cmd.ZuulApp):

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description='Zuul merge worker.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-d', dest='nodaemon', action='store_true',
                            help='do not run as a daemon')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
                            help='show zuul version')
        self.args = parser.parse_args()

    def exit_handler(self, signum, frame):
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        self.merger.stop()
        self.merger.join()

    def main(self):
        # See comment at top of file about zuul imports
        import zuul.merger.server

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
    server = Merger()
    server.parse_arguments()

    server.read_config()
    server.configure_connections()

    if server.config.has_option('zuul', 'state_dir'):
        state_dir = os.path.expanduser(server.config.get('zuul', 'state_dir'))
    else:
        state_dir = '/var/lib/zuul'
    test_fn = os.path.join(state_dir, 'test')
    try:
        f = open(test_fn, 'w')
        f.close()
        os.unlink(test_fn)
    except Exception:
        print("\nUnable to write to state directory: %s\n" % state_dir)
        raise

    if server.config.has_option('merger', 'pidfile'):
        pid_fn = os.path.expanduser(server.config.get('merger', 'pidfile'))
    else:
        pid_fn = '/var/run/zuul-merger/zuul-merger.pid'
    pid = pid_file_module.TimeoutPIDLockFile(pid_fn, 10)

    if server.args.nodaemon:
        server.main()
    else:
        with daemon.DaemonContext(pidfile=pid):
            server.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
