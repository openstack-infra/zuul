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

import logging
import os
import sys
import signal

import zuul.cmd
import zuul.executor.client
import zuul.merger.client
import zuul.nodepool
import zuul.scheduler
import zuul.zk

from zuul.lib.config import get_default
from zuul.lib.statsd import get_statsd_config


class Scheduler(zuul.cmd.ZuulDaemonApp):
    app_name = 'scheduler'
    app_description = 'The main zuul process.'

    def __init__(self):
        super(Scheduler, self).__init__()
        self.gear_server_pid = None

    def createParser(self):
        parser = super(Scheduler, self).createParser()
        parser.add_argument('command',
                            choices=zuul.scheduler.COMMANDS,
                            nargs='?')
        return parser

    def parseArguments(self, args=None):
        super(Scheduler, self).parseArguments()
        if self.args.command:
            self.args.nodaemon = True

    def reconfigure_handler(self, signum, frame):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.log.debug("Reconfiguration triggered")
        self.readConfig()
        self.setup_logging('scheduler', 'log_config')
        try:
            self.sched.reconfigure(self.config)
        except Exception:
            self.log.exception("Reconfiguration failed:")
        signal.signal(signal.SIGHUP, self.reconfigure_handler)

    def exit_handler(self, signum, frame):
        self.sched.exit()
        self.sched.join()
        self.stop_gear_server()
        sys.exit(0)

    def start_gear_server(self):
        pipe_read, pipe_write = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(pipe_write)
            self.setup_logging('gearman_server', 'log_config')
            import zuul.lib.gearserver

            (statsd_host, statsd_port, statsd_prefix) = get_statsd_config(
                self.config)
            if statsd_prefix:
                statsd_prefix += '.zuul.geard'
            else:
                statsd_prefix = 'zuul.geard'

            host = get_default(self.config, 'gearman_server', 'listen_address')
            port = int(get_default(self.config, 'gearman_server', 'port',
                                   4730))
            ssl_key = get_default(self.config, 'gearman_server', 'ssl_key')
            ssl_cert = get_default(self.config, 'gearman_server', 'ssl_cert')
            ssl_ca = get_default(self.config, 'gearman_server', 'ssl_ca')
            zuul.lib.gearserver.GearServer(port,
                                           ssl_key=ssl_key,
                                           ssl_cert=ssl_cert,
                                           ssl_ca=ssl_ca,
                                           host=host,
                                           statsd_host=statsd_host,
                                           statsd_port=statsd_port,
                                           statsd_prefix=statsd_prefix,
                                           keepalive=True,
                                           tcp_keepidle=300,
                                           tcp_keepintvl=60,
                                           tcp_keepcnt=5)

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

    def run(self):
        if self.args.command in zuul.scheduler.COMMANDS:
            self.send_command(self.args.command)
            sys.exit(0)

        if (self.config.has_option('gearman_server', 'start') and
            self.config.getboolean('gearman_server', 'start')):
            self.start_gear_server()

        self.setup_logging('scheduler', 'log_config')
        self.log = logging.getLogger("zuul.Scheduler")

        self.sched = zuul.scheduler.Scheduler(self.config)

        gearman = zuul.executor.client.ExecutorClient(self.config, self.sched)
        merger = zuul.merger.client.MergeClient(self.config, self.sched)
        nodepool = zuul.nodepool.Nodepool(self.sched)

        zookeeper = zuul.zk.ZooKeeper()
        zookeeper_hosts = get_default(self.config, 'zookeeper',
                                      'hosts', '127.0.0.1:2181')
        zookeeper_timeout = float(get_default(self.config, 'zookeeper',
                                              'session_timeout', 10.0))

        zookeeper.connect(zookeeper_hosts, timeout=zookeeper_timeout)

        self.configure_connections()
        self.sched.setExecutor(gearman)
        self.sched.setMerger(merger)
        self.sched.setNodepool(nodepool)
        self.sched.setZooKeeper(zookeeper)

        self.log.info('Starting scheduler')
        try:
            self.sched.start()
            self.sched.registerConnections(self.connections)
            self.sched.reconfigure(self.config)
            self.sched.resume()
        except Exception:
            self.log.exception("Error starting Zuul:")
            # TODO(jeblair): If we had all threads marked as daemon,
            # we might be able to have a nicer way of exiting here.
            self.sched.stop()
            sys.exit(1)

        signal.signal(signal.SIGHUP, self.reconfigure_handler)

        if self.args.nodaemon:
            signal.signal(signal.SIGTERM, self.exit_handler)
            while True:
                try:
                    signal.pause()
                except KeyboardInterrupt:
                    print("Ctrl + C: asking scheduler to exit nicely...\n")
                    self.exit_handler(signal.SIGINT, None)
        else:
            self.sched.join()


def main():
    Scheduler().main()


if __name__ == "__main__":
    main()
