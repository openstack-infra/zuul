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
import logging
import logging.config
import os
import sys

import zuul.rpcclient


class Client(object):
    log = logging.getLogger("zuul.Client")

    def __init__(self):
        self.args = None
        self.config = None
        self.gear_server_pid = None

    def parse_arguments(self):
        parser = argparse.ArgumentParser(
            description='Zuul Project Gating System Client.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-v', dest='verbose', action='store_true',
                            help='verbose output')
        parser.add_argument('--version', dest='version', action='store_true',
                            help='show zuul version')

        subparsers = parser.add_subparsers(title='commands',
                                           description='valid commands',
                                           help='additional help')

        cmd_enqueue = subparsers.add_parser('enqueue', help='enqueue a change')
        cmd_enqueue.add_argument('--trigger', help='trigger name',
                                 required=True)
        cmd_enqueue.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_enqueue.add_argument('--project', help='project name',
                                 required=True)
        cmd_enqueue.add_argument('--change', help='change id',
                                 required=True)
        cmd_enqueue.add_argument('--patchset', help='patchset number',
                                 required=True)
        cmd_enqueue.set_defaults(func=self.enqueue)

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
        if self.args.verbose:
            logging.basicConfig(level=logging.DEBUG)

    def main(self):
        self.parse_arguments()
        self.read_config()
        self.setup_logging()

        if self.args.version:
            from zuul.version import version_info as zuul_version_info
            print "Zuul version: %s" % zuul_version_info.version_string()
            sys.exit(0)

        self.server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            self.port = self.config.get('gearman', 'port')
        else:
            self.port = 4730

        if self.args.func():
            sys.exit(0)
        else:
            sys.exit(1)

    def enqueue(self):
        client = zuul.rpcclient.RPCClient(self.server, self.port)
        r = client.enqueue(pipeline=self.args.pipeline,
                           project=self.args.project,
                           trigger=self.args.trigger,
                           change=self.args.change,
                           patchset=self.args.patchset)
        return r


def main():
    client = Client()
    client.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
