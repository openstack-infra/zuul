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

import six
from six.moves import configparser as ConfigParser
import extras
import logging
import logging.config
import os
import signal
import sys
import traceback

yappi = extras.try_import('yappi')

import zuul.lib.connections

# Do not import modules that will pull in paramiko which must not be
# imported until after the daemonization.
# https://github.com/paramiko/paramiko/issues/59
# Similar situation with gear and statsd.


def stack_dump_handler(signum, frame):
    signal.signal(signal.SIGUSR2, signal.SIG_IGN)
    log_str = ""
    for thread_id, stack_frame in sys._current_frames().items():
        log_str += "Thread: %s\n" % thread_id
        log_str += "".join(traceback.format_stack(stack_frame))
    log = logging.getLogger("zuul.stack_dump")
    log.debug(log_str)
    if yappi:
        if not yappi.is_running():
            yappi.start()
        else:
            yappi.stop()
            yappi_out = six.BytesIO()
            yappi.get_func_stats().print_all(out=yappi_out)
            yappi.get_thread_stats().print_all(out=yappi_out)
            log.debug(yappi_out.getvalue())
            yappi_out.close()
            yappi.clear_stats()
    signal.signal(signal.SIGUSR2, stack_dump_handler)


class ZuulApp(object):

    def __init__(self):
        self.args = None
        self.config = None
        self.connections = {}

    def _get_version(self):
        from zuul.version import version_info as zuul_version_info
        return "Zuul version: %s" % zuul_version_info.release_string()

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

    def configure_connections(self):
        self.connections = zuul.lib.connections.configure_connections(
            self.config)
