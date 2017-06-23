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
from zuul.lib.config import get_default

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


class Scheduler(zuul.cmd.ZuulApp):
    def __init__(self):
        super(Scheduler, self).__init__()
        self.gear_server_pid = None

    def parse_arguments(self, args=None):
        parser = argparse.ArgumentParser(description='Project gating system.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-d', dest='nodaemon', action='store_true',
                            help='do not run as a daemon')
        parser.add_argument('-t', dest='validate', action='store_true',
                            help='validate config file syntax (Does not'
                            'validate config repo validity)')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
                            help='show zuul version')
        self.args = parser.parse_args(args)

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

    def test_config(self):
        # See comment at top of file about zuul imports
        import zuul.scheduler
        import zuul.executor.client

        logging.basicConfig(level=logging.DEBUG)
        try:
            self.sched = zuul.scheduler.Scheduler(self.config,
                                                  testonly=True)
        except Exception as e:
            self.log.error("%s" % e)
            return -1
        return 0

    def start_gear_server(self):
        pipe_read, pipe_write = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(pipe_write)
            self.setup_logging('gearman_server', 'log_config')
            import zuul.lib.gearserver
            statsd_host = os.environ.get('STATSD_HOST')
            statsd_port = int(os.environ.get('STATSD_PORT', 8125))
            host = get_default(self.config, 'gearman_server', 'listen_address')
            ssl_key = get_default(self.config, 'gearman_server', 'ssl_key')
            ssl_cert = get_default(self.config, 'gearman_server', 'ssl_cert')
            ssl_ca = get_default(self.config, 'gearman_server', 'ssl_ca')
            zuul.lib.gearserver.GearServer(4730,
                                           ssl_key=ssl_key,
                                           ssl_cert=ssl_cert,
                                           ssl_ca=ssl_ca,
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
        import zuul.executor.client
        import zuul.merger.client
        import zuul.nodepool
        import zuul.webapp
        import zuul.rpclistener
        import zuul.zk

        signal.signal(signal.SIGUSR2, zuul.cmd.stack_dump_handler)
        if (self.config.has_option('gearman_server', 'start') and
            self.config.getboolean('gearman_server', 'start')):
            self.start_gear_server()

        self.setup_logging('zuul', 'log_config')
        self.log = logging.getLogger("zuul.Scheduler")

        self.sched = zuul.scheduler.Scheduler(self.config)

        gearman = zuul.executor.client.ExecutorClient(self.config, self.sched)
        merger = zuul.merger.client.MergeClient(self.config, self.sched)
        nodepool = zuul.nodepool.Nodepool(self.sched)

        zookeeper = zuul.zk.ZooKeeper()
        zookeeper_hosts = get_default(self.config, 'zuul', 'zookeeper_hosts',
                                      '127.0.0.1:2181')

        zookeeper.connect(zookeeper_hosts)

        cache_expiry = get_default(self.config, 'webapp', 'status_expiry', 1)
        listen_address = get_default(self.config, 'webapp', 'listen_address',
                                     '0.0.0.0')
        port = get_default(self.config, 'webapp', 'port', 8001)

        webapp = zuul.webapp.WebApp(
            self.sched, port=port, cache_expiry=cache_expiry,
            listen_address=listen_address)
        rpc = zuul.rpclistener.RPCListener(self.config, self.sched)

        self.configure_connections()
        self.sched.setExecutor(gearman)
        self.sched.setMerger(merger)
        self.sched.setNodepool(nodepool)
        self.sched.setZooKeeper(zookeeper)

        self.log.info('Starting scheduler')
        try:
            self.sched.start()
            self.sched.registerConnections(self.connections, webapp)
            self.sched.reconfigure(self.config)
            self.sched.resume()
        except Exception:
            self.log.exception("Error starting Zuul:")
            # TODO(jeblair): If we had all threads marked as daemon,
            # we might be able to have a nicer way of exiting here.
            sys.exit(1)
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
    scheduler = Scheduler()
    scheduler.parse_arguments()

    scheduler.read_config()

    if scheduler.args.validate:
        sys.exit(scheduler.test_config())

    pid_fn = get_default(scheduler.config, 'zuul', 'pidfile',
                         '/var/run/zuul-scheduler/zuul-scheduler.pid',
                         expand_user=True)
    pid = pid_file_module.TimeoutPIDLockFile(pid_fn, 10)

    if scheduler.args.nodaemon:
        scheduler.main()
    else:
        with daemon.DaemonContext(pidfile=pid):
            scheduler.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
