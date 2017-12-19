# Copyright 2014 OpenStack Foundation
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
from uuid import uuid4

import gear

import zuul.model
from zuul.lib.config import get_default


def getJobData(job):
    if not len(job.data):
        return {}
    d = job.data[-1]
    if not d:
        return {}
    return json.loads(d)


class MergeGearmanClient(gear.Client):
    def __init__(self, merge_client):
        super(MergeGearmanClient, self).__init__('Zuul Merge Client')
        self.__merge_client = merge_client

    def handleWorkComplete(self, packet):
        job = super(MergeGearmanClient, self).handleWorkComplete(packet)
        self.__merge_client.onBuildCompleted(job)
        return job

    def handleWorkFail(self, packet):
        job = super(MergeGearmanClient, self).handleWorkFail(packet)
        self.__merge_client.onBuildCompleted(job)
        return job

    def handleWorkException(self, packet):
        job = super(MergeGearmanClient, self).handleWorkException(packet)
        self.__merge_client.onBuildCompleted(job)
        return job

    def handleDisconnect(self, job):
        job = super(MergeGearmanClient, self).handleDisconnect(job)
        self.__merge_client.onBuildCompleted(job)


class MergeJob(gear.TextJob):
    def __init__(self, *args, **kw):
        super(MergeJob, self).__init__(*args, **kw)
        self.__event = threading.Event()

    def setComplete(self):
        self.__event.set()

    def wait(self, timeout=300):
        return self.__event.wait(timeout)


class MergeClient(object):
    log = logging.getLogger("zuul.MergeClient")

    def __init__(self, config, sched):
        self.config = config
        self.sched = sched
        server = self.config.get('gearman', 'server')
        port = get_default(self.config, 'gearman', 'port', 4730)
        ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')
        self.log.debug("Connecting to gearman at %s:%s" % (server, port))
        self.gearman = MergeGearmanClient(self)
        self.gearman.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for gearman")
        self.gearman.waitForServer()
        self.jobs = set()

    def stop(self):
        self.gearman.shutdown()

    def areMergesOutstanding(self):
        if self.jobs:
            return True
        return False

    def submitJob(self, name, data, build_set,
                  precedence=zuul.model.PRECEDENCE_NORMAL):
        uuid = str(uuid4().hex)
        job = MergeJob(name,
                       json.dumps(data),
                       unique=uuid)
        job.build_set = build_set
        self.log.debug("Submitting job %s with data %s" % (job, data))
        self.jobs.add(job)
        self.gearman.submitJob(job, precedence=precedence,
                               timeout=300)
        return job

    def mergeChanges(self, items, build_set, files=None, dirs=None,
                     repo_state=None, precedence=zuul.model.PRECEDENCE_NORMAL):
        data = dict(items=items,
                    files=files,
                    dirs=dirs,
                    repo_state=repo_state)
        self.submitJob('merger:merge', data, build_set, precedence)

    def getRepoState(self, items, build_set,
                     precedence=zuul.model.PRECEDENCE_NORMAL):
        data = dict(items=items)
        self.submitJob('merger:refstate', data, build_set, precedence)

    def getFiles(self, connection_name, project_name, branch, files, dirs=[],
                 precedence=zuul.model.PRECEDENCE_HIGH):
        data = dict(connection=connection_name,
                    project=project_name,
                    branch=branch,
                    files=files,
                    dirs=dirs)
        job = self.submitJob('merger:cat', data, None, precedence)
        return job

    def getFilesChanges(self, connection_name, project_name, branch,
                        tosha=None, precedence=zuul.model.PRECEDENCE_HIGH):
        data = dict(connection=connection_name,
                    project=project_name,
                    branch=branch,
                    tosha=tosha)
        job = self.submitJob('merger:fileschanges', data, None, precedence)
        return job

    def onBuildCompleted(self, job):
        data = getJobData(job)
        merged = data.get('merged', False)
        job.updated = data.get('updated', False)
        commit = data.get('commit')
        files = data.get('files', {})
        repo_state = data.get('repo_state', {})
        job.files = files
        self.log.info("Merge %s complete, merged: %s, updated: %s, "
                      "commit: %s" %
                      (job, merged, job.updated, commit))
        job.setComplete()
        if job.build_set:
            self.sched.onMergeCompleted(job.build_set,
                                        merged, job.updated, commit, files,
                                        repo_state)
        # The test suite expects the job to be removed from the
        # internal account after the wake flag is set.
        self.jobs.remove(job)
