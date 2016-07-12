#!/usr/bin/env python
# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
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
import sys
import signal

import zuul.cmd

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


class Server(zuul.cmd.ZuulApp):
    def __init__(self):
        super(Server, self).__init__()
        self.gear_server_pid = None

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description='Project gating system.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-l', dest='layout',
                            help='specify the layout file')
        parser.add_argument('-d', dest='nodaemon', action='store_true',
                            help='do not run as a daemon')
        parser.add_argument('-t', dest='validate', nargs='?', const=True,
                            metavar='JOB_LIST',
                            help='validate layout file syntax (optionally '
                            'providing the path to a file with a list of '
                            'available job names)')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
                            help='show zuul version')
        self.args = parser.parse_args()

    def reconfigure_handler(self, signum, frame):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.log.debug("Reconfiguration triggered")
        self.read_config()
        self.setup_logging('zuul', 'log_config')
        try:
            self.sched.reconfigure(self.config)
        except Exception:
            self.log.exception("Reconfiguration failed:")
        signal.signal(signal.SIGHUP, self.reconfigure_handler)

    def exit_handler(self, signum, frame):
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        self.sched.exit()
        self.sched.join()
        self.stop_gear_server()

    def term_handler(self, signum, frame):
        self.stop_gear_server()
        os._exit(0)

    def test_config(self, job_list_path):
        # See comment at top of file about zuul imports
        import zuul.scheduler
        import zuul.launcher.gearman
        import zuul.trigger.gerrit

        logging.basicConfig(level=logging.DEBUG)
        self.sched = zuul.scheduler.Scheduler(self.config,
                                              testonly=True)
        self.configure_connections()
        self.sched.registerConnections(self.connections, load=False)
        layout = self.sched.testConfig(self.config.get('zuul',
                                                       'layout_config'),
                                       self.connections)
        if not job_list_path:
            return False

        failure = False
        path = os.path.expanduser(job_list_path)
        if not os.path.exists(path):
            raise Exception("Unable to find job list: %s" % path)
        jobs = set()
        jobs.add('noop')
        for line in open(path):
            v = line.strip()
            if v:
                jobs.add(v)
        for job in sorted(layout.jobs):
            if job not in jobs:
                print("FAILURE: Job %s not defined" % job)
                failure = True
        return failure

    def start_gear_server(self):
        pipe_read, pipe_write = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(pipe_write)
            self.setup_logging('gearman_server', 'log_config')
            import zuul.lib.gearserver
            statsd_host = os.environ.get('STATSD_HOST')
            statsd_port = int(os.environ.get('STATSD_PORT', 8125))
            if self.config.has_option('gearman_server', 'listen_address'):
                host = self.config.get('gearman_server', 'listen_address')
            else:
                host = None
            zuul.lib.gearserver.GearServer(4730,
                                           host=host,
                                           statsd_host=statsd_host,
                                           statsd_port=statsd_port,
                                           statsd_prefix='zuul.geard')

            # Keep running until the parent dies:
            pipe_read = os.fdopen(pipe_read)
            pipe_read.read()
            os._exit(0)
        else:
            os.close(pipe_read)
            self.gear_server_pid = child_pid
            self.gear_pipe_write = pipe_write

    def stop_gear_server(self):
        if self.gear_server_pid:
            os.kill(self.gear_server_pid, signal.SIGKILL)

    def main(self):
        # See comment at top of file about zuul imports
        import zuul.scheduler
        import zuul.launcher.gearman
        import zuul.merger.client
        import zuul.lib.swift
        import zuul.webapp
        import zuul.rpclistener

        signal.signal(signal.SIGUSR2, zuul.cmd.stack_dump_handler)
        if (self.config.has_option('gearman_server', 'start') and
            self.config.getboolean('gearman_server', 'start')):
            self.start_gear_server()

        self.setup_logging('zuul', 'log_config')
        self.log = logging.getLogger("zuul.Server")

        self.sched = zuul.scheduler.Scheduler(self.config)
        # TODO(jhesketh): Move swift into a connection?
        self.swift = zuul.lib.swift.Swift(self.config)

        gearman = zuul.launcher.gearman.Gearman(self.config, self.sched,
                                                self.swift)
        merger = zuul.merger.client.MergeClient(self.config, self.sched)

        if self.config.has_option('zuul', 'status_expiry'):
            cache_expiry = self.config.getint('zuul', 'status_expiry')
        else:
            cache_expiry = 1

        if self.config.has_option('webapp', 'listen_address'):
            listen_address = self.config.get('webapp', 'listen_address')
        else:
            listen_address = '0.0.0.0'

        if self.config.has_option('webapp', 'port'):
            port = self.config.getint('webapp', 'port')
        else:
            port = 8001

        webapp = zuul.webapp.WebApp(
            self.sched, port=port, cache_expiry=cache_expiry,
            listen_address=listen_address)
        rpc = zuul.rpclistener.RPCListener(self.config, self.sched)

        self.configure_connections()
        self.sched.setLauncher(gearman)
        self.sched.setMerger(merger)

        self.log.info('Starting scheduler')
        self.sched.start()
        self.sched.registerConnections(self.connections)
        self.sched.reconfigure(self.config)
        self.sched.resume()
        self.log.info('Starting Webapp')
        webapp.start()
        self.log.info('Starting RPC')
        rpc.start()

        signal.signal(signal.SIGHUP, self.reconfigure_handler)
        signal.signal(signal.SIGUSR1, self.exit_handler)
        signal.signal(signal.SIGTERM, self.term_handler)
        while True:
            try:
                signal.pause()
            except KeyboardInterrupt:
                print("Ctrl + C: asking scheduler to exit nicely...\n")
                self.exit_handler(signal.SIGINT, None)


def main():
    server = Server()
    server.parse_arguments()

    server.read_config()

    if server.args.layout:
        server.config.set('zuul', 'layout_config', server.args.layout)

    if server.args.validate:
        path = server.args.validate
        if path is True:
            path = None
        sys.exit(server.test_config(path))

    if server.config.has_option('zuul', 'pidfile'):
        pid_fn = os.path.expanduser(server.config.get('zuul', 'pidfile'))
    else:
        pid_fn = '/var/run/zuul/zuul.pid'
    pid = pid_file_module.TimeoutPIDLockFile(pid_fn, 10)

    if server.args.nodaemon:
        server.main()
    else:
        with daemon.DaemonContext(pidfile=pid):
            server.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
