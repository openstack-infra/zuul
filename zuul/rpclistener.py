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
import six

from zuul import model


class RPCListener(object):
    log = logging.getLogger("zuul.RPCListener")

    def __init__(self, config, sched):
        self.config = config
        self.sched = sched

    def start(self):
        self._running = True
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.worker = gear.Worker('Zuul RPC Listener')
        self.worker.addServer(server, port)
        self.worker.waitForServer()
        self.register()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("zuul:enqueue")
        self.worker.registerFunction("zuul:enqueue_ref")
        self.worker.registerFunction("zuul:promote")
        self.worker.registerFunction("zuul:get_running_jobs")

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
            except Exception:
                self.log.exception("Exception while getting job")

    def _common_enqueue(self, job):
        args = json.loads(job.arguments)
        event = model.TriggerEvent()
        errors = ''

        trigger = self.sched.triggers.get(args['trigger'])
        if trigger:
            event.trigger_name = args['trigger']
        else:
            errors += 'Invalid trigger: %s\n' % (args['trigger'],)

        project = self.sched.layout.projects.get(args['project'])
        if project:
            event.project_name = args['project']
        else:
            errors += 'Invalid project: %s\n' % (args['project'],)

        pipeline = self.sched.layout.pipelines.get(args['pipeline'])
        if pipeline:
            event.forced_pipeline = args['pipeline']
        else:
            errors += 'Invalid pipeline: %s\n' % (args['pipeline'],)

        return (args, event, errors, pipeline, project)

    def handle_enqueue(self, job):
        (args, event, errors, pipeline, project) = self._common_enqueue(job)

        if not errors:
            event.change_number, event.patch_number = args['change'].split(',')
            try:
                pipeline.source.getChange(event, project)
            except Exception:
                errors += 'Invalid change: %s\n' % (args['change'],)

        if errors:
            job.sendWorkException(errors.encode('utf8'))
        else:
            self.sched.enqueue(event)
            job.sendWorkComplete()

    def handle_enqueue_ref(self, job):
        (args, event, errors, pipeline, project) = self._common_enqueue(job)

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
        pipeline_name = args['pipeline']
        change_ids = args['change_ids']
        self.sched.promote(pipeline_name, change_ids)
        job.sendWorkComplete()

    def handle_get_running_jobs(self, job):
        # args = json.loads(job.arguments)
        # TODO: use args to filter by pipeline etc
        running_items = []
        for pipeline_name, pipeline in six.iteritems(
                self.sched.layout.pipelines):
            for queue in pipeline.queues:
                for item in queue.queue:
                    running_items.append(item.formatJSON())

        job.sendWorkComplete(json.dumps(running_items))
