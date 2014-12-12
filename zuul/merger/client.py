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
from uuid import uuid4

import gear

import zuul.model


def getJobData(job):
    if not len(job.data):
        return {}
    d = job.data[-1]
    if not d:
        return {}
    return json.loads(d)


class MergeGearmanClient(gear.Client):
    def __init__(self, merge_client):
        super(MergeGearmanClient, self).__init__()
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


class MergeClient(object):
    log = logging.getLogger("zuul.MergeClient")

    def __init__(self, config, sched):
        self.config = config
        self.sched = sched
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.log.debug("Connecting to gearman at %s:%s" % (server, port))
        self.gearman = MergeGearmanClient(self)
        self.gearman.addServer(server, port)
        self.log.debug("Waiting for gearman")
        self.gearman.waitForServer()
        self.build_sets = {}

    def stop(self):
        self.gearman.shutdown()

    def areMergesOutstanding(self):
        if self.build_sets:
            return True
        return False

    def submitJob(self, name, data, build_set,
                  precedence=zuul.model.PRECEDENCE_NORMAL):
        uuid = str(uuid4().hex)
        self.log.debug("Submitting job %s with data %s" % (name, data))
        job = gear.Job(name,
                       json.dumps(data),
                       unique=uuid)
        self.build_sets[uuid] = build_set
        self.gearman.submitJob(job, precedence=precedence,
                               timeout=300)

    def mergeChanges(self, items, build_set,
                     precedence=zuul.model.PRECEDENCE_NORMAL):
        data = dict(items=items)
        self.submitJob('merger:merge', data, build_set, precedence)

    def updateRepo(self, project, url, build_set,
                   precedence=zuul.model.PRECEDENCE_NORMAL):
        data = dict(project=project,
                    url=url)
        self.submitJob('merger:update', data, build_set, precedence)

    def onBuildCompleted(self, job):
        build_set = self.build_sets.get(job.unique)
        if build_set:
            data = getJobData(job)
            zuul_url = data.get('zuul_url')
            merged = data.get('merged', False)
            updated = data.get('updated', False)
            commit = data.get('commit')
            self.log.info("Merge %s complete, merged: %s, updated: %s, "
                          "commit: %s" %
                          (job, merged, updated, build_set.commit))
            self.sched.onMergeCompleted(build_set, zuul_url,
                                        merged, updated, commit)
            # The test suite expects the build_set to be removed from
            # the internal dict after the wake flag is set.
            del self.build_sets[job.unique]
        else:
            self.log.error("Unable to find build set for uuid %s" % job.unique)
