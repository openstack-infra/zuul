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
import types

import gear

from zuul import model
from zuul.lib import encryption
from zuul.lib.config import get_default


class MappingProxyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, types.MappingProxyType):
            return dict(obj)
        return json.JSONEncoder.default(self, obj)


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
        self.worker.addServer(server, port, ssl_key, ssl_cert, ssl_ca,
                              keepalive=True, tcp_keepidle=60,
                              tcp_keepintvl=30, tcp_keepcnt=5)
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
        self.worker.registerFunction("zuul:dequeue")
        self.worker.registerFunction("zuul:enqueue")
        self.worker.registerFunction("zuul:enqueue_ref")
        self.worker.registerFunction("zuul:promote")
        self.worker.registerFunction("zuul:get_running_jobs")
        self.worker.registerFunction("zuul:get_job_log_stream_address")
        self.worker.registerFunction("zuul:tenant_list")
        self.worker.registerFunction("zuul:tenant_sql_connection")
        self.worker.registerFunction("zuul:status_get")
        self.worker.registerFunction("zuul:job_get")
        self.worker.registerFunction("zuul:job_list")
        self.worker.registerFunction("zuul:project_get")
        self.worker.registerFunction("zuul:project_list")
        self.worker.registerFunction("zuul:pipeline_list")
        self.worker.registerFunction("zuul:key_get")
        self.worker.registerFunction("zuul:config_errors_list")

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

    def handle_dequeue(self, job):
        args = json.loads(job.arguments)
        tenant_name = args['tenant']
        pipeline_name = args['pipeline']
        project_name = args['project']
        change = args['change']
        ref = args['ref']
        try:
            self.sched.dequeue(
                tenant_name, pipeline_name, project_name, change, ref)
        except Exception as e:
            job.sendWorkException(str(e).encode('utf8'))
            return
        job.sendWorkComplete()

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

        if args['change'] and args['ref']:
            job.sendWorkException("Change and ref can't be both used "
                                  "for the same request")

        if args['change']:
            # Convert change into ref based on zuul connection
            ref_filter = project.source.getRefForChange(args['change'])
        elif args['ref']:
            ref_filter = "%s" % args['ref']
        else:
            ref_filter = ".*"

        params['job_name'] = args['job']
        params['ref_filter'] = ref_filter
        params['reason'] = args['reason']

        if args['count'] < 0:
            error = "Invalid count: %d" % args['count']
            job.sendWorkException(error.encode('utf8'))
            return

        params['count'] = args['count']
        params['node_hold_expiration'] = args['node_hold_expiration']

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
                ch = project.source.getChange(event, refresh=True)
                if ch.project.name != project.name:
                    errors += ('Change %s does not belong to project "%s", '
                               % (args['change'], project.name))
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
            try:
                int(event.oldrev, 16)
                if len(event.oldrev) != 40:
                    errors += 'Old rev must be 40 character sha1: ' \
                              '%s\n' % event.oldrev
            except Exception:
                errors += 'Old rev must be base16 hash: ' \
                          '%s\n' % event.oldrev
            try:
                int(event.newrev, 16)
                if len(event.newrev) != 40:
                    errors += 'New rev must be 40 character sha1: ' \
                              '%s\n' % event.newrev
            except Exception:
                errors += 'New rev must be base16 hash: ' \
                          '%s\n' % event.newrev

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
            queue_size = 0
            for pipeline_name, pipeline in tenant.layout.pipelines.items():
                for queue in pipeline.queues:
                    for item in queue.queue:
                        if item.live:
                            queue_size += 1

            output.append({'name': tenant_name,
                           'projects': len(tenant.untrusted_projects),
                           'queue': queue_size})
        job.sendWorkComplete(json.dumps(output))

    def handle_tenant_sql_connection(self, job):
        args = json.loads(job.arguments)
        sql_driver = self.sched.connections.drivers['sql']
        conn = sql_driver.tenant_connections.get(args['tenant'])
        if conn:
            name = conn.connection_name
        else:
            name = ''
        job.sendWorkComplete(json.dumps(name))

    def handle_status_get(self, job):
        args = json.loads(job.arguments)
        output = self.sched.formatStatusJSON(args.get("tenant"))
        job.sendWorkComplete(output)

    def handle_job_get(self, gear_job):
        args = json.loads(gear_job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        if not tenant:
            gear_job.sendWorkComplete(json.dumps(None))
            return
        jobs = tenant.layout.jobs.get(args.get("job"), [])
        output = []
        for job in jobs:
            output.append(job.toDict(tenant))
        gear_job.sendWorkComplete(json.dumps(output, cls=MappingProxyEncoder))

    def handle_job_list(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        output = []
        if not tenant:
            job.sendWorkComplete(json.dumps(None))
        for job_name in sorted(tenant.layout.jobs):
            desc = None
            variants = []
            for variant in tenant.layout.jobs[job_name]:
                if not desc and variant.description:
                    desc = variant.description.split('\n')[0]
                job_variant = {}
                if not variant.isBase():
                    if variant.parent:
                        job_variant['parent'] = str(variant.parent)
                    else:
                        job_variant['parent'] = tenant.default_base_job
                branches = variant.getBranches()
                if branches:
                    job_variant['branches'] = branches
                if job_variant:
                    variants.append(job_variant)

            job_output = {
                "name": job_name,
            }
            if desc:
                job_output["description"] = desc
            if variants:
                job_output["variants"] = variants
            output.append(job_output)
        job.sendWorkComplete(json.dumps(output))

    def handle_project_get(self, gear_job):
        args = json.loads(gear_job.arguments)
        tenant = self.sched.abide.tenants.get(args["tenant"])
        if not tenant:
            gear_job.sendWorkComplete(json.dumps(None))
            return
        trusted, project = tenant.getProject(args["project"])
        if not project:
            gear_job.sendWorkComplete(json.dumps({}))
            return
        result = project.toDict()
        result['configs'] = []
        configs = tenant.layout.getAllProjectConfigs(project.canonical_name)
        for config_obj in configs:
            config = config_obj.toDict()
            config['pipelines'] = []
            for pipeline_name, pipeline_config in sorted(
                    config_obj.pipelines.items()):
                pipeline = pipeline_config.toDict()
                pipeline['name'] = pipeline_name
                pipeline['jobs'] = []
                for jobs in pipeline_config.job_list.jobs.values():
                    job_list = []
                    for job in jobs:
                        job_list.append(job.toDict(tenant))
                    pipeline['jobs'].append(job_list)
                config['pipelines'].append(pipeline)
            result['configs'].append(config)

        gear_job.sendWorkComplete(json.dumps(result, cls=MappingProxyEncoder))

    def handle_project_list(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        if not tenant:
            job.sendWorkComplete(json.dumps(None))
            return
        output = []
        for project in tenant.config_projects:
            pobj = project.toDict()
            pobj['type'] = "config"
            output.append(pobj)
        for project in tenant.untrusted_projects:
            pobj = project.toDict()
            pobj['type'] = "untrusted"
            output.append(pobj)
        job.sendWorkComplete(json.dumps(
            sorted(output, key=lambda project: project["name"])))

    def handle_pipeline_list(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        if not tenant:
            job.sendWorkComplete(json.dumps(None))
            return
        output = []
        for pipeline in tenant.layout.pipelines.keys():
            output.append({"name": pipeline})
        job.sendWorkComplete(json.dumps(output))

    def handle_key_get(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        project = None
        if tenant:
            (trusted, project) = tenant.getProject(args.get("project"))
        if not project:
            job.sendWorkComplete("")
            return
        keytype = args.get('key', 'secrets')
        if keytype == 'secrets':
            job.sendWorkComplete(
                encryption.serialize_rsa_public_key(
                    project.public_secrets_key))
        elif keytype == 'ssh':
            job.sendWorkComplete(project.public_ssh_key)
        else:
            job.sendWorkComplete("")
            return

    def handle_config_errors_list(self, job):
        args = json.loads(job.arguments)
        tenant = self.sched.abide.tenants.get(args.get("tenant"))
        output = []
        if not tenant:
            job.sendWorkComplete(json.dumps(None))
            return
        for err in tenant.layout.loading_errors.errors:
            output.append({
                'source_context': err.key.context.toDict(),
                'error': err.error})
        job.sendWorkComplete(json.dumps(output))
