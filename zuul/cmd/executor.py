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

import logging
import os
import pwd
import socket
import sys
import signal
import tempfile

import zuul.cmd
import zuul.executor.server

# No zuul imports that pull in paramiko here; it must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


DEFAULT_FINGER_PORT = 79


class Executor(zuul.cmd.ZuulApp):

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description='Zuul executor.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-d', dest='nodaemon', action='store_true',
                            help='do not run as a daemon')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
                            help='show zuul version')
        parser.add_argument('--keep-jobdir', dest='keep_jobdir',
                            action='store_true',
                            help='keep local jobdirs after run completes')
        parser.add_argument('command',
                            choices=zuul.executor.server.COMMANDS,
                            nargs='?')

        self.args = parser.parse_args()

    def send_command(self, cmd):
        if self.config.has_option('zuul', 'state_dir'):
            state_dir = os.path.expanduser(
                self.config.get('zuul', 'state_dir'))
        else:
            state_dir = '/var/lib/zuul'
        path = os.path.join(state_dir, 'executor.socket')
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(path)
        s.sendall('%s\n' % cmd)

    def exit_handler(self):
        self.executor.stop()
        self.executor.join()

    def start_log_streamer(self):
        pipe_read, pipe_write = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(pipe_write)
            import zuul.lib.log_streamer

            self.log.info("Starting log streamer")
            streamer = zuul.lib.log_streamer.LogStreamer(
                self.user, '0.0.0.0', self.finger_port, self.jobroot_dir)

            # Keep running until the parent dies:
            pipe_read = os.fdopen(pipe_read)
            pipe_read.read()
            self.log.info("Stopping log streamer")
            streamer.stop()
            os._exit(0)
        else:
            os.close(pipe_read)
            self.log_streamer_pid = child_pid

    def change_privs(self):
        '''
        Drop our privileges to the zuul user.
        '''
        if os.getuid() != 0:
            return
        pw = pwd.getpwnam(self.user)
        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.umask(0o022)

    def main(self, daemon=True):
        # See comment at top of file about zuul imports

        if self.config.has_option('executor', 'user'):
            self.user = self.config.get('executor', 'user')
        else:
            self.user = 'zuul'

        if self.config.has_option('zuul', 'jobroot_dir'):
            self.jobroot_dir = os.path.expanduser(
                self.config.get('zuul', 'jobroot_dir'))
        else:
            self.jobroot_dir = tempfile.gettempdir()

        self.setup_logging('executor', 'log_config')
        self.log = logging.getLogger("zuul.Executor")

        if self.config.has_option('executor', 'finger_port'):
            self.finger_port = int(self.config.get('executor', 'finger_port'))
        else:
            self.finger_port = DEFAULT_FINGER_PORT

        self.start_log_streamer()
        self.change_privs()

        ExecutorServer = zuul.executor.server.ExecutorServer
        self.executor = ExecutorServer(self.config, self.connections,
                                       jobdir_root=self.jobroot_dir,
                                       keep_jobdir=self.args.keep_jobdir)
        self.executor.start()

        signal.signal(signal.SIGUSR2, zuul.cmd.stack_dump_handler)
        if daemon:
            self.executor.join()
        else:
            while True:
                try:
                    signal.pause()
                except KeyboardInterrupt:
                    print("Ctrl + C: asking executor to exit nicely...\n")
                    self.exit_handler()
                    sys.exit(0)


def main():
    server = Executor()
    server.parse_arguments()
    server.read_config()

    if server.args.command in zuul.executor.server.COMMANDS:
        server.send_command(server.args.command)
        sys.exit(0)

    server.configure_connections(source_only=True)

    if server.config.has_option('executor', 'pidfile'):
        pid_fn = os.path.expanduser(server.config.get('executor', 'pidfile'))
    else:
        pid_fn = '/var/run/zuul-executor/zuul-executor.pid'
    pid = pid_file_module.TimeoutPIDLockFile(pid_fn, 10)

    if server.args.nodaemon:
        server.main(False)
    else:
        with daemon.DaemonContext(pidfile=pid):
            server.main(True)


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
