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
import babel.dates
import datetime
import logging
import prettytable
import sys
import time


import zuul.rpcclient
import zuul.cmd


class Client(zuul.cmd.ZuulApp):
    log = logging.getLogger("zuul.Client")

    def parse_arguments(self):
        parser = argparse.ArgumentParser(
            description='Zuul Project Gating System Client.')
        parser.add_argument('-c', dest='config',
                            help='specify the config file')
        parser.add_argument('-v', dest='verbose', action='store_true',
                            help='verbose output')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
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
        cmd_enqueue.set_defaults(func=self.enqueue)

        cmd_promote = subparsers.add_parser('promote',
                                            help='promote one or more changes')
        cmd_promote.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_promote.add_argument('--changes', help='change ids',
                                 required=True, nargs='+')
        cmd_promote.set_defaults(func=self.promote)

        cmd_show = subparsers.add_parser('show',
                                         help='valid show subcommands')
        show_subparsers = cmd_show.add_subparsers(title='show')
        show_running_jobs = show_subparsers.add_parser(
            'running-jobs',
            help='show the running jobs'
        )
        show_running_jobs.add_argument(
            '--columns',
            help="comma separated list of columns to display (or 'ALL')",
            choices=self._show_running_jobs_columns().keys().append('ALL'),
            default='name, worker.name, start_time, result'
        )

        # TODO: add filters such as queue, project, changeid etc
        show_running_jobs.set_defaults(func=self.show_running_jobs)

        self.args = parser.parse_args()

    def setup_logging(self):
        """Client logging does not rely on conf file"""
        if self.args.verbose:
            logging.basicConfig(level=logging.DEBUG)

    def main(self):
        self.parse_arguments()
        self.read_config()
        self.setup_logging()

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
                           change=self.args.change)
        return r

    def promote(self):
        client = zuul.rpcclient.RPCClient(self.server, self.port)
        r = client.promote(pipeline=self.args.pipeline,
                           change_ids=self.args.changes)
        return r

    def show_running_jobs(self):
        client = zuul.rpcclient.RPCClient(self.server, self.port)
        running_items = client.get_running_jobs()

        if len(running_items) == 0:
            print "No jobs currently running"
            return True

        all_fields = self._show_running_jobs_columns()
        if self.args.columns.upper() == 'ALL':
            fields = all_fields.keys()
        else:
            fields = [f.strip().lower() for f in self.args.columns.split(',')
                      if f.strip().lower() in all_fields.keys()]

        table = prettytable.PrettyTable(
            field_names=[all_fields[f]['title'] for f in fields])
        for item in running_items:
            for job in item['jobs']:
                values = []
                for f in fields:
                    v = job
                    for part in f.split('.'):
                        if hasattr(v, 'get'):
                            v = v.get(part, '')
                    if ('transform' in all_fields[f]
                        and callable(all_fields[f]['transform'])):
                        v = all_fields[f]['transform'](v)
                    if 'append' in all_fields[f]:
                        v += all_fields[f]['append']
                    values.append(v)
                table.add_row(values)
        print table
        return True

    def _epoch_to_relative_time(self, epoch):
        if epoch:
            delta = datetime.timedelta(seconds=(time.time() - int(epoch)))
            return babel.dates.format_timedelta(delta, locale='en_US')
        else:
            return "Unknown"

    def _boolean_to_yes_no(self, value):
        return 'Yes' if value else 'No'

    def _boolean_to_pass_fail(self, value):
        return 'Pass' if value else 'Fail'

    def _format_list(self, l):
        return ', '.join(l) if isinstance(l, list) else ''

    def _show_running_jobs_columns(self):
        """A helper function to get the list of available columns for
        `zuul show running-jobs`. Also describes how to convert particular
        values (for example epoch to time string)"""

        return {
            'name': {
                'title': 'Job Name',
            },
            'elapsed_time': {
                'title': 'Elapsed Time',
                'transform': self._epoch_to_relative_time
            },
            'remaining_time': {
                'title': 'Remaining Time',
                'transform': self._epoch_to_relative_time
            },
            'url': {
                'title': 'URL'
            },
            'result': {
                'title': 'Result'
            },
            'voting': {
                'title': 'Voting',
                'transform': self._boolean_to_yes_no
            },
            'uuid': {
                'title': 'UUID'
            },
            'launch_time': {
                'title': 'Launch Time',
                'transform': self._epoch_to_relative_time,
                'append': ' ago'
            },
            'start_time': {
                'title': 'Start Time',
                'transform': self._epoch_to_relative_time,
                'append': ' ago'
            },
            'end_time': {
                'title': 'End Time',
                'transform': self._epoch_to_relative_time,
                'append': ' ago'
            },
            'estimated_time': {
                'title': 'Estimated Time',
                'transform': self._epoch_to_relative_time,
                'append': ' to go'
            },
            'pipeline': {
                'title': 'Pipeline'
            },
            'canceled': {
                'title': 'Canceled',
                'transform': self._boolean_to_yes_no
            },
            'retry': {
                'title': 'Retry'
            },
            'number': {
                'title': 'Number'
            },
            'worker.name': {
                'title': 'Worker'
            },
            'worker.hostname': {
                'title': 'Worker Hostname'
            },
            'worker.ips': {
                'title': 'Worker IPs',
                'transform': self._format_list
            },
            'worker.fqdn': {
                'title': 'Worker Domain'
            },
            'worker.progam': {
                'title': 'Worker Program'
            },
            'worker.version': {
                'title': 'Worker Version'
            },
            'worker.extra': {
                'title': 'Worker Extra'
            },
        }


def main():
    client = Client()
    client.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
