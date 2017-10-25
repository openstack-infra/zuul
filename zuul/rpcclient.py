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
import time

import gear


class RPCFailure(Exception):
    pass


class RPCClient(object):
    log = logging.getLogger("zuul.RPCClient")

    def __init__(self, server, port, ssl_key=None, ssl_cert=None, ssl_ca=None):
        self.log.debug("Connecting to gearman at %s:%s" % (server, port))
        self.gearman = gear.Client()
        self.gearman.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for gearman")
        self.gearman.waitForServer()

    def submitJob(self, name, data):
        self.log.debug("Submitting job %s with data %s" % (name, data))
        job = gear.TextJob(name,
                           json.dumps(data),
                           unique=str(time.time()))
        self.gearman.submitJob(job, timeout=300)

        self.log.debug("Waiting for job completion")
        while not job.complete:
            time.sleep(0.1)
        if job.exception:
            raise RPCFailure(job.exception)
        self.log.debug("Job complete, success: %s" % (not job.failure))
        return job

    def autohold(self, tenant, project, job, change, ref, reason, count):
        data = {'tenant': tenant,
                'project': project,
                'job': job,
                'change': change,
                'ref': ref,
                'reason': reason,
                'count': count}
        return not self.submitJob('zuul:autohold', data).failure

    def autohold_list(self):
        data = {}
        job = self.submitJob('zuul:autohold_list', data)
        if job.failure:
            return False
        else:
            return json.loads(job.data[0])

    def enqueue(self, tenant, pipeline, project, trigger, change):
        data = {'tenant': tenant,
                'pipeline': pipeline,
                'project': project,
                'trigger': trigger,
                'change': change,
                }
        return not self.submitJob('zuul:enqueue', data).failure

    def enqueue_ref(
            self, tenant, pipeline, project, trigger, ref, oldrev, newrev):
        data = {'tenant': tenant,
                'pipeline': pipeline,
                'project': project,
                'trigger': trigger,
                'ref': ref,
                'oldrev': oldrev,
                'newrev': newrev,
                }
        return not self.submitJob('zuul:enqueue_ref', data).failure

    def promote(self, tenant, pipeline, change_ids):
        data = {'tenant': tenant,
                'pipeline': pipeline,
                'change_ids': change_ids,
                }
        return not self.submitJob('zuul:promote', data).failure

    def get_running_jobs(self):
        data = {}
        job = self.submitJob('zuul:get_running_jobs', data)
        if job.failure:
            return False
        else:
            return json.loads(job.data[0])

    def shutdown(self):
        self.gearman.shutdown()

    def get_job_log_stream_address(self, uuid, logfile='console.log'):
        data = {'uuid': uuid, 'logfile': logfile}
        job = self.submitJob('zuul:get_job_log_stream_address', data)
        if job.failure:
            return False
        else:
            return json.loads(job.data[0])
