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

import json
import logging
import threading
import traceback

import gear

from zuul import model
from zuul.lib import encryption
from zuul.lib.config import get_default


class RPCListener(object):
    log = logging.getLogger("zuul.RPCListener")

    def __init__(self, config, sched):
        self.config = config
        self.sched = sched

    def start(self):
        self._running = True
        server = self.config.get('gearman', 'server')
        port = get_default(self.config, 'gearman', 'port', 4730)
        ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')
        self.worker = gear.TextWorker('Zuul RPC Listener')
        self.worker.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.log.debug("Registering")
        self.register()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("zuul:autohold")
        self.worker.registerFunction("zuul:autohold_list")
        self.worker.registerFunction("zuul:enqueue")
        self.worker.registerFunction("zuul:enqueue_ref")
        self.worker.registerFunction("zuul:promote")
        self.worker.registerFunction("zuul:get_running_jobs")
        self.worker.registerFunction("zuul:get_job_log_stream_address")
        self.worker.registerFunction("zuul:tenant_list")
        self.worker.registerFunction("zuul:status_get")
        self.worker.registerFunction("zuul:job_list")
        self.worker.registerFunction("zuul:key_get")

    def getFunctions(self):
        functions = {}
        for connection in self.worker.active_connections:
            try:
                req = gear.StatusAdminRequest()
                connection.sendAdminRequest(req, timeout=300)
            except Exception:
                self.log.exception("Exception while listing functions")
                self.worker._lostConnection(connection)
                continue
            for line in req.response.decode('utf8').split('\n'):
                parts = [x.strip() for x in line.split('\t')]
                if len(parts) < 4:
                    continue
                # parts[0] - function name
                # parts[1] - total jobs queued (including building)
                # parts[2] - jobs building
                # parts[3] - workers registered
                data = functions.setdefault(parts[0], [0, 0, 0])
                for i in range(3):
                    data[i] += int(parts[i + 1])
        return functions

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self.worker.shutdown()
        self.log.debug("Stopped")

    def join(self):
        self.thread.join()

    def run(self):
        self.log.debug("Starting RPC listener")
        while self._running:
            try:
                job = self.worker.getJob()
                self.log.debug("Received job %s" % job.name)
                z, jobname = job.name.split(':')
                attrname = 'handle_' + jobname
                if hasattr(self, attrname):
                    f = getattr(self, attrname)
                    if callable(f):
                        try:
                            f(job)
                        except Exception:
                            self.log.exception("Exception while running job")
                            job.sendWorkException(traceback.format_exc())
                    else:
                        job.sendWorkFail()
                else:
                    job.sendWorkFail()
            except gear.InterruptedError:
                return
            except Exception:
                self.log.exception("Exception while getting job")

    def handle_autohold_list(self, job):
        req = {}

        # The json.dumps() call cannot handle dict keys that are not strings
        # so we convert our key to a CSV string that the caller can parse.
        for key, value in self.sched.autohold_requests.items():
            new_key = ','.join(key)
            req[new_key] = value

        job.sendWorkComplete(json.dumps(req))

    def handle_autohold(self, job):
        args = json.loads(job.arguments)
        params = {}

        tenant = self.sched.abide.tenants.get(args['tenant'])
        if tenant:
            params['tenant_name'] = args['tenant']
        else:
            error = "Invalid tenant: %s" % args['tenant']
            job.sendWorkException(error.encode('utf8'))
            return

        (trusted, project) = tenant.getProject(args['project'])
        if project:
            params['project_name'] = project.canonical_name
        else:
            error = "Invalid project: %s" % args['project']
            job.sendWorkException(error.encode('utf8'))
            return

        params['job_name'] = args['job']
        params['reason'] = args['reason']

        if args['count'] < 0:
            error = "Invalid count: %d" % args['count']
            job.sendWorkException(error.encode('utf8'))
            return

        params['count'] = args['count']

        self.sched.autohold(**params)
        job.sendWorkComplete()

    def _common_enqueue(self, job):
        args = json.loads(job.arguments)
        event = model.TriggerEvent()
        errors = ''
        tenant = None
        project = None
        pipeline = None

        tenant = self.sched.abide.tenants.get(args['tenant'])
        if tenant:
            event.tenant_name = args['tenant']

            (trusted, project) = tenant.getProject(args['project'])
            if project:
                event.project_hostname = project.canonical_hostname
                event.project_name = project.name
            else:
                errors += 'Invalid project: %s\n' % (args['project'],)

            pipeline = tenant.layout.pipelines.get(args['pipeline'])
            if pipeline:
                event.forced_pipeline = args['pipeline']

                for trigger in pipeline.triggers:
                    if trigger.name == args['trigger']:
                        event.trigger_name = args['trigger']
                        continue
                if not event.trigger_name:
                    errors += 'Invalid trigger: %s\n' % (args['trigger'],)
            else:
                errors += 'Invalid pipeline: %s\n' % (args['pipeline'],)
        else:
            errors += 'Invalid tenant: %s\n' % (args['tenant'],)

        return (args, event, errors, project)

    def handle_enqueue(self, job):
        (args, event, errors, project) = self._common_enqueue(job)

        if not errors:
            event.change_number, event.patch_number = args['change'].split(',')
            try:
                project.source.getChange(event, project)
            except Exception:
                errors += 'Invalid change: %s\n' % (args['change'],)

        if errors:
            job.sendWorkException(errors.encode('utf8'))
        else:
            self.sched.enqueue(event)
            job.sendWorkComplete()

    def handle_enqueue_ref(self, job):
        (args, event, errors, project) = self._common_enqueue(job)

        if not errors:
            event.ref = args['ref']
            event.oldrev = args['oldrev']
            event.newrev = args['newrev']

        if errors:
            job.sendWorkException(errors.encode('utf8'))
        else:
            self.sched.enqueue(event)
            job.sendWorkComplete()

    def handle_promote(self, job):
        args = json.loads(job.arguments)
        tenant_name = args['tenant']
        pipeline_name = args['pipeline']
        change_ids = args['change_ids']
        self.sched.promote(tenant_name, pipeline_name, change_ids)
        job.sendWorkComplete()

    def handle_get_running_jobs(self, job):
        # args = json.loads(job.arguments)
        # TODO: use args to filter by pipeline etc
        running_items = []
        for tenant in self.sched.abide.tenants.values():
            for pipeline_name, pipeline in tenant.layout.pipelines.items():
                for queue in pipeline.queues:
                    for item in queue.queue:
                        running_items.append(item.formatJSON())

        job.sendWorkComplete(json.dumps(running_items))

    def handle_get_job_log_stream_address(self, job):
        # TODO: map log files to ports. Currently there is only one
        #       log stream for a given job. But many jobs produce many
        #       log files, so this is forwards compatible with a future
        #       where there are more logs to potentially request than
        #       "console.log"
        def find_build(uuid):
            for tenant in self.sched.abide.tenants.values():
                for pipeline_name, pipeline in tenant.layout.pipelines.items():
                    for queue in pipeline.queues:
                        for item in queue.queue:
                            for bld in item.current_build_set.getBuilds():
                                if bld.uuid == uuid:
                                    return bld
            return None

        args = json.loads(job.arguments)
        uuid = args['uuid']
        # TODO: logfile = args['logfile']
        job_log_stream_address = {}
        build = find_build(uuid)
        if build:
            job_log_stream_address['server'] = build.worker.hostname
            job_log_stream_address['port'] = build.worker.log_port
        job.sendWorkComplete(json.dumps(job_log_stream_address))

    def handle_tenant_list(self, job):
        output = []
        for tenant_name, tenant in self.sched.abide.tenants.items():
            output.append({'name': tenant_name,
                           'projects': len(tenant.untrusted_projects)})
        job.sendWorkComplete(json.dumps(output))

    def handle_status_get(self, job):
        args = json.loads(job.arguments)
        output = self.sched.formatStatusJSON(args.get("tenant"))
        job.sendWorkComplete(output)

    def handle_job_list(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        output = []
        for job_name in sorted(tenant.layout.jobs):
            desc = None
            for tenant_job in tenant.layout.jobs[job_name]:
                if tenant_job.description:
                    desc = tenant_job.description.split('\n')[0]
                    break
            output.append({"name": job_name,
                           "description": desc})
        job.sendWorkComplete(json.dumps(output))

    def handle_key_get(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        (trusted, project) = tenant.getProject(args.get("project"))
        job.sendWorkComplete(
            encryption.serialize_rsa_public_key(project.public_key))
