# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import logging.config
import os
import signal

# No zuul imports here because they pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59


class Server(object):
    def __init__(self):
        self.args = None
        self.config = None

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description='Project gating system.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-d', dest='nodaemon', action='store_true',
                            help='do not run as a daemon')
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

    def setup_logging(self):
        if self.config.has_option('zuul', 'log_config'):
            fp = os.path.expanduser(self.config.get('zuul', 'log_config'))
            if not os.path.exists(fp):
                raise Exception("Unable to read logging config file at %s" %
                                fp)
            logging.config.fileConfig(fp)
        else:
            logging.basicConfig(level=logging.DEBUG)

    def reconfigure_handler(self, signum, frame):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.read_config()
        self.setup_logging()
        self.sched.reconfigure(self.config)
        signal.signal(signal.SIGHUP, self.reconfigure_handler)

    def exit_handler(self, signum, frame):
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        self.sched.exit()

    def main(self):
        # See comment at top of file about zuul imports
        import zuul.scheduler
        import zuul.launcher.jenkins
        import zuul.trigger.gerrit

        self.sched = zuul.scheduler.Scheduler()

        jenkins = zuul.launcher.jenkins.Jenkins(self.config, self.sched)
        gerrit = zuul.trigger.gerrit.Gerrit(self.config, self.sched)

        self.sched.setLauncher(jenkins)
        self.sched.setTrigger(gerrit)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()
        signal.signal(signal.SIGHUP, self.reconfigure_handler)
        signal.signal(signal.SIGUSR1, self.exit_handler)
        while True:
            try:
                signal.pause()
            except KeyboardInterrupt:
                print "Ctrl + C: asking scheduler to exit nicely...\n"
                self.exit_handler(signal.SIGINT, None)


def main():
    server = Server()
    server.parse_arguments()
    server.read_config()

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
        server.setup_logging()
        server.main()
    else:
        with daemon.DaemonContext(pidfile=pid):
            server.setup_logging()
            server.main()
