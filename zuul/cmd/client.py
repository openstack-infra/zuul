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
import textwrap


import zuul.rpcclient
import zuul.cmd
from zuul.lib.config import get_default


class Client(zuul.cmd.ZuulApp):
    app_name = 'zuul'
    app_description = 'Zuul RPC client.'
    log = logging.getLogger("zuul.Client")

    def createParser(self):
        parser = super(Client, self).createParser()
        parser.add_argument('-v', dest='verbose', action='store_true',
                            help='verbose output')

        subparsers = parser.add_subparsers(title='commands',
                                           description='valid commands',
                                           help='additional help')

        cmd_autohold = subparsers.add_parser(
            'autohold', help='hold nodes for failed job')
        cmd_autohold.add_argument('--tenant', help='tenant name',
                                  required=True)
        cmd_autohold.add_argument('--project', help='project name',
                                  required=True)
        cmd_autohold.add_argument('--job', help='job name',
                                  required=True)
        cmd_autohold.add_argument('--change',
                                  help='specific change to hold nodes for',
                                  required=False, default='')
        cmd_autohold.add_argument('--ref', help='git ref to hold nodes for',
                                  required=False, default='')
        cmd_autohold.add_argument('--reason', help='reason for the hold',
                                  required=True)
        cmd_autohold.add_argument('--count',
                                  help='number of job runs (default: 1)',
                                  required=False, type=int, default=1)
        cmd_autohold.add_argument('--node-hold-expiration',
                                  help=('how long in seconds should the '
                                        'node set be in HOLD status '
                                        '(default: nodepool\'s max-hold-age '
                                        'if set, or indefinitely)'),
                                  required=False, default=0)
        cmd_autohold.set_defaults(func=self.autohold)

        cmd_autohold_list = subparsers.add_parser(
            'autohold-list', help='list autohold requests')
        cmd_autohold_list.set_defaults(func=self.autohold_list)

        cmd_enqueue = subparsers.add_parser('enqueue', help='enqueue a change')
        cmd_enqueue.add_argument('--tenant', help='tenant name',
                                 required=True)
        cmd_enqueue.add_argument('--trigger', help='trigger name',
                                 required=True)
        cmd_enqueue.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_enqueue.add_argument('--project', help='project name',
                                 required=True)
        cmd_enqueue.add_argument('--change', help='change id',
                                 required=True)
        cmd_enqueue.set_defaults(func=self.enqueue)

        cmd_enqueue = subparsers.add_parser(
            'enqueue-ref', help='enqueue a ref',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent('''\
            Submit a trigger event

            Directly enqueue a trigger event.  This is usually used
            to manually "replay" a trigger received from an external
            source such as gerrit.'''))
        cmd_enqueue.add_argument('--tenant', help='tenant name',
                                 required=True)
        cmd_enqueue.add_argument('--trigger', help='trigger name',
                                 required=True)
        cmd_enqueue.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_enqueue.add_argument('--project', help='project name',
                                 required=True)
        cmd_enqueue.add_argument('--ref', help='ref name',
                                 required=True)
        cmd_enqueue.add_argument(
            '--oldrev', help='old revision', default=None)
        cmd_enqueue.add_argument(
            '--newrev', help='new revision', default=None)
        cmd_enqueue.set_defaults(func=self.enqueue_ref)

        cmd_dequeue = subparsers.add_parser('dequeue',
                                            help='dequeue a buildset by its '
                                                 'change or ref')
        cmd_dequeue.add_argument('--tenant', help='tenant name',
                                 required=True)
        cmd_dequeue.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_dequeue.add_argument('--project', help='project name',
                                 required=True)
        cmd_dequeue.add_argument('--change', help='change id',
                                 default=None)
        cmd_dequeue.add_argument('--ref', help='ref name',
                                 default=None)
        cmd_dequeue.set_defaults(func=self.dequeue)

        cmd_promote = subparsers.add_parser('promote',
                                            help='promote one or more changes')
        cmd_promote.add_argument('--tenant', help='tenant name',
                                 required=True)
        cmd_promote.add_argument('--pipeline', help='pipeline name',
                                 required=True)
        cmd_promote.add_argument('--changes', help='change ids',
                                 required=True, nargs='+')
        cmd_promote.set_defaults(func=self.promote)

        cmd_show = subparsers.add_parser('show',
                                         help='show current statuses')
        cmd_show.set_defaults(func=self.show_running_jobs)
        show_subparsers = cmd_show.add_subparsers(title='show')
        show_running_jobs = show_subparsers.add_parser(
            'running-jobs',
            help='show the running jobs'
        )
        running_jobs_columns = list(self._show_running_jobs_columns().keys())
        show_running_jobs.add_argument(
            '--columns',
            help="comma separated list of columns to display (or 'ALL')",
            choices=running_jobs_columns.append('ALL'),
            default='name, worker.name, start_time, result'
        )

        # TODO: add filters such as queue, project, changeid etc
        show_running_jobs.set_defaults(func=self.show_running_jobs)

        cmd_conf_check = subparsers.add_parser(
            'tenant-conf-check',
            help='validate the tenant configuration')
        cmd_conf_check.set_defaults(func=self.validate)

        return parser

    def parseArguments(self, args=None):
        parser = super(Client, self).parseArguments()
        if not getattr(self.args, 'func', None):
            parser.print_help()
            sys.exit(1)
        if self.args.func == self.enqueue_ref:
            # if oldrev or newrev is set, ensure they're not the same
            if (self.args.oldrev is not None) or \
               (self.args.newrev is not None):
                if self.args.oldrev == self.args.newrev:
                    parser.error(
                        "The old and new revisions must not be the same.")
            # if they're not set, we pad them out to zero
            if self.args.oldrev is None:
                self.args.oldrev = '0000000000000000000000000000000000000000'
            if self.args.newrev is None:
                self.args.newrev = '0000000000000000000000000000000000000000'
        if self.args.func == self.dequeue:
            if self.args.change is None and self.args.ref is None:
                parser.error("Change or ref needed.")
            if self.args.change is not None and self.args.ref is not None:
                parser.error(
                    "The 'change' and 'ref' arguments are mutually exclusive.")

    def setup_logging(self):
        """Client logging does not rely on conf file"""
        if self.args.verbose:
            logging.basicConfig(level=logging.DEBUG)

    def main(self):
        self.parseArguments()
        self.readConfig()
        self.setup_logging()

        self.server = self.config.get('gearman', 'server')
        self.port = get_default(self.config, 'gearman', 'port', 4730)
        self.ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        self.ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        self.ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')

        if self.args.func():
            sys.exit(0)
        else:
            sys.exit(1)

    def autohold(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        if self.args.change and self.args.ref:
            print("Change and ref can't be both used for the same request")
            return False
        if "," in self.args.change:
            print("Error: change argument can not contain any ','")
            return False

        node_hold_expiration = self.args.node_hold_expiration
        r = client.autohold(tenant=self.args.tenant,
                            project=self.args.project,
                            job=self.args.job,
                            change=self.args.change,
                            ref=self.args.ref,
                            reason=self.args.reason,
                            count=self.args.count,
                            node_hold_expiration=node_hold_expiration)
        return r

    def autohold_list(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        autohold_requests = client.autohold_list()

        if len(autohold_requests.keys()) == 0:
            print("No autohold requests found")
            return True

        table = prettytable.PrettyTable(
            field_names=[
                'Tenant', 'Project', 'Job', 'Ref Filter', 'Count', 'Reason'
            ])

        for key, value in autohold_requests.items():
            # The key comes to us as a CSV string because json doesn't like
            # non-str keys.
            tenant_name, project_name, job_name, ref_filter = key.split(',')
            count, reason, node_hold_expiration = value

            table.add_row([
                tenant_name, project_name, job_name, ref_filter, count, reason
            ])
        print(table)
        return True

    def enqueue(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        r = client.enqueue(tenant=self.args.tenant,
                           pipeline=self.args.pipeline,
                           project=self.args.project,
                           trigger=self.args.trigger,
                           change=self.args.change)
        return r

    def enqueue_ref(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        r = client.enqueue_ref(tenant=self.args.tenant,
                               pipeline=self.args.pipeline,
                               project=self.args.project,
                               trigger=self.args.trigger,
                               ref=self.args.ref,
                               oldrev=self.args.oldrev,
                               newrev=self.args.newrev)
        return r

    def dequeue(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        r = client.dequeue(tenant=self.args.tenant,
                           pipeline=self.args.pipeline,
                           project=self.args.project,
                           change=self.args.change,
                           ref=self.args.ref)
        return r

    def promote(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        r = client.promote(tenant=self.args.tenant,
                           pipeline=self.args.pipeline,
                           change_ids=self.args.changes)
        return r

    def show_running_jobs(self):
        client = zuul.rpcclient.RPCClient(
            self.server, self.port, self.ssl_key, self.ssl_cert, self.ssl_ca)
        running_items = client.get_running_jobs()

        if len(running_items) == 0:
            print("No jobs currently running")
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
        print(table)
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
            'execute_time': {
                'title': 'Execute Time',
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
            'node_labels': {
                'title': 'Node Labels'
            },
            'node_name': {
                'title': 'Node Name'
            },
            'worker.name': {
                'title': 'Worker'
            },
            'worker.hostname': {
                'title': 'Worker Hostname'
            },
        }

    def validate(self):
        from zuul import scheduler
        from zuul import configloader
        sched = scheduler.Scheduler(self.config, testonly=True)
        self.configure_connections(source_only=True)
        sched.registerConnections(self.connections, load=False)
        loader = configloader.ConfigLoader(
            sched.connections, sched, None)
        tenant_config, script = sched._checkTenantSourceConf(self.config)
        unparsed_abide = loader.readConfig(tenant_config, from_script=script)
        try:
            for conf_tenant in unparsed_abide.tenants:
                loader.tenant_parser.getSchema()(conf_tenant)
            print("Tenants config validated with success")
            err_code = 0
        except Exception as e:
            print("Error when validating tenants config")
            print(e)
            err_code = 1
        finally:
            sys.exit(err_code)


def main():
    Client().main()


if __name__ == "__main__":
    main()
