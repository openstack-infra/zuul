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
import ConfigParser
import daemon
import extras

# as of python-daemon 1.6 it doesn't bundle pidlockfile anymore
# instead it depends on lockfile-0.9.1 which uses pidfile.
pid_file_module = extras.try_imports(['daemon.pidlockfile', 'daemon.pidfile'])

import logging
import logging.config
import os
import sys
import signal
import traceback

import gear

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59


def stack_dump_handler(signum, frame):
    signal.signal(signal.SIGUSR2, signal.SIG_IGN)
    log_str = ""
    for thread_id, stack_frame in sys._current_frames().items():
        log_str += "Thread: %s\n" % thread_id
        log_str += "".join(traceback.format_stack(stack_frame))
    log = logging.getLogger("zuul.stack_dump")
    log.debug(log_str)
    signal.signal(signal.SIGUSR2, stack_dump_handler)


class Server(object):
    def __init__(self):
        self.args = None
        self.config = None
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
        parser.add_argument('--version', dest='version', action='store_true',
                            help='show zuul version')
        self.args = parser.parse_args()

    def read_config(self):
        self.config = ConfigParser.ConfigParser()
        if self.args.config:
            locations = [self.args.config]
        else:
            locations = ['/etc/zuul/zuul.conf',
                         '~/zuul.conf']
        for fp in locations:
            if os.path.exists(os.path.expanduser(fp)):
                self.config.read(os.path.expanduser(fp))
                return
        raise Exception("Unable to locate config file in %s" % locations)

    def setup_logging(self, section, parameter):
        if self.config.has_option(section, parameter):
            fp = os.path.expanduser(self.config.get(section, parameter))
            if not os.path.exists(fp):
                raise Exception("Unable to read logging config file at %s" %
                                fp)
            logging.config.fileConfig(fp)
        else:
            logging.basicConfig(level=logging.DEBUG)

    def reconfigure_handler(self, signum, frame):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.read_config()
        self.setup_logging('zuul', 'log_config')
        self.sched.reconfigure(self.config)
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
        self.sched = zuul.scheduler.Scheduler()
        self.sched.registerReporter(None, 'gerrit')
        self.sched.registerReporter(None, 'smtp')
        self.sched.registerTrigger(None, 'gerrit')
        self.sched.registerTrigger(None, 'timer')
        layout = self.sched.testConfig(self.config.get('zuul',
                                                       'layout_config'))
        if not job_list_path:
            return False

        failure = False
        path = os.path.expanduser(job_list_path)
        if not os.path.exists(path):
            raise Exception("Unable to find job list: %s" % path)
        jobs = set()
        for line in open(path):
            v = line.strip()
            if v:
                jobs.add(v)
        for job in sorted(layout.jobs):
            if job not in jobs:
                print "Job %s not defined" % job
                failure = True
        return failure

    def start_gear_server(self):
        pipe_read, pipe_write = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(pipe_write)
            self.setup_logging('gearman_server', 'log_config')
            gear.Server(4730)
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
        import zuul.reporter.gerrit
        import zuul.reporter.smtp
        import zuul.trigger.gerrit
        import zuul.trigger.timer
        import zuul.webapp
        import zuul.rpclistener

        if (self.config.has_option('gearman_server', 'start') and
            self.config.getboolean('gearman_server', 'start')):
            self.start_gear_server()

        self.setup_logging('zuul', 'log_config')

        self.sched = zuul.scheduler.Scheduler()

        gearman = zuul.launcher.gearman.Gearman(self.config, self.sched)
        gerrit = zuul.trigger.gerrit.Gerrit(self.config, self.sched)
        timer = zuul.trigger.timer.Timer(self.config, self.sched)
        webapp = zuul.webapp.WebApp(self.sched)
        rpc = zuul.rpclistener.RPCListener(self.config, self.sched)
        gerrit_reporter = zuul.reporter.gerrit.Reporter(gerrit)
        smtp_reporter = zuul.reporter.smtp.Reporter(
            self.config.get('smtp', 'default_from')
            if self.config.has_option('smtp', 'default_from') else 'zuul',
            self.config.get('smtp', 'default_to')
            if self.config.has_option('smtp', 'default_to') else 'zuul',
            self.config.get('smtp', 'server')
            if self.config.has_option('smtp', 'server') else 'localhost',
            self.config.get('smtp', 'port')
            if self.config.has_option('smtp', 'port') else 25
        )

        self.sched.setLauncher(gearman)
        self.sched.registerTrigger(gerrit)
        self.sched.registerTrigger(timer)
        self.sched.registerReporter(gerrit_reporter)
        self.sched.registerReporter(smtp_reporter)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()
        webapp.start()
        rpc.start()

        signal.signal(signal.SIGHUP, self.reconfigure_handler)
        signal.signal(signal.SIGUSR1, self.exit_handler)
        signal.signal(signal.SIGUSR2, stack_dump_handler)
        signal.signal(signal.SIGTERM, self.term_handler)
        while True:
            try:
                signal.pause()
            except KeyboardInterrupt:
                print "Ctrl + C: asking scheduler to exit nicely...\n"
                self.exit_handler(signal.SIGINT, None)


def main():
    server = Server()
    server.parse_arguments()

    if server.args.version:
        from zuul.version import version_info as zuul_version_info
        print "Zuul version: %s" % zuul_version_info.version_string()
        sys.exit(0)

    server.read_config()

    if server.args.layout:
        server.config.set('zuul', 'layout_config', server.args.layout)

    if server.args.validate:
        path = server.args.validate
        if path is True:
            path = None
        sys.exit(server.test_config(path))

    if server.config.has_option('zuul', 'state_dir'):
        state_dir = os.path.expanduser(server.config.get('zuul', 'state_dir'))
    else:
        state_dir = '/var/lib/zuul'
    test_fn = os.path.join(state_dir, 'test')
    try:
        f = open(test_fn, 'w')
        f.close()
        os.unlink(test_fn)
    except:
        print
        print "Unable to write to state directory: %s" % state_dir
        print
        raise

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
