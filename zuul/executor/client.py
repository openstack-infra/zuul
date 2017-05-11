# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import copy
import gear
import json
import logging
import time
import threading
from uuid import uuid4

import zuul.model
from zuul.model import Build


class GearmanCleanup(threading.Thread):
    """ A thread that checks to see if outstanding builds have
    completed without reporting back. """
    log = logging.getLogger("zuul.GearmanCleanup")

    def __init__(self, gearman):
        threading.Thread.__init__(self)
        self.daemon = True
        self.gearman = gearman
        self.wake_event = threading.Event()
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.wake_event.set()

    def run(self):
        while True:
            self.wake_event.wait(300)
            if self._stopped:
                return
            try:
                self.gearman.lookForLostBuilds()
            except:
                self.log.exception("Exception checking builds:")


def getJobData(job):
    if not len(job.data):
        return {}
    d = job.data[-1]
    if not d:
        return {}
    return json.loads(d)


class ZuulGearmanClient(gear.Client):
    def __init__(self, zuul_gearman):
        super(ZuulGearmanClient, self).__init__('Zuul Executor Client')
        self.__zuul_gearman = zuul_gearman

    def handleWorkComplete(self, packet):
        job = super(ZuulGearmanClient, self).handleWorkComplete(packet)
        self.__zuul_gearman.onBuildCompleted(job)
        return job

    def handleWorkFail(self, packet):
        job = super(ZuulGearmanClient, self).handleWorkFail(packet)
        self.__zuul_gearman.onBuildCompleted(job)
        return job

    def handleWorkException(self, packet):
        job = super(ZuulGearmanClient, self).handleWorkException(packet)
        self.__zuul_gearman.onBuildCompleted(job)
        return job

    def handleWorkStatus(self, packet):
        job = super(ZuulGearmanClient, self).handleWorkStatus(packet)
        self.__zuul_gearman.onWorkStatus(job)
        return job

    def handleWorkData(self, packet):
        job = super(ZuulGearmanClient, self).handleWorkData(packet)
        self.__zuul_gearman.onWorkStatus(job)
        return job

    def handleDisconnect(self, job):
        job = super(ZuulGearmanClient, self).handleDisconnect(job)
        self.__zuul_gearman.onDisconnect(job)

    def handleStatusRes(self, packet):
        try:
            job = super(ZuulGearmanClient, self).handleStatusRes(packet)
        except gear.UnknownJobError:
            handle = packet.getArgument(0)
            for build in self.__zuul_gearman.builds:
                if build.__gearman_job.handle == handle:
                    self.__zuul_gearman.onUnknownJob(job)


class ExecutorClient(object):
    log = logging.getLogger("zuul.ExecutorClient")
    negative_function_cache_ttl = 5

    def __init__(self, config, sched):
        self.config = config
        self.sched = sched
        self.builds = {}
        self.meta_jobs = {}  # A list of meta-jobs like stop or describe

        server = config.get('gearman', 'server')
        if config.has_option('gearman', 'port'):
            port = config.get('gearman', 'port')
        else:
            port = 4730

        self.gearman = ZuulGearmanClient(self)
        self.gearman.addServer(server, port)

        self.cleanup_thread = GearmanCleanup(self)
        self.cleanup_thread.start()
        self.function_cache = set()
        self.function_cache_time = 0

    def stop(self):
        self.log.debug("Stopping")
        self.cleanup_thread.stop()
        self.cleanup_thread.join()
        self.gearman.shutdown()
        self.log.debug("Stopped")

    def isJobRegistered(self, name):
        if self.function_cache_time:
            for connection in self.gearman.active_connections:
                if connection.connect_time > self.function_cache_time:
                    self.function_cache = set()
                    self.function_cache_time = 0
                    break
        if name in self.function_cache:
            self.log.debug("Function %s is registered" % name)
            return True
        if ((time.time() - self.function_cache_time) <
            self.negative_function_cache_ttl):
            self.log.debug("Function %s is not registered "
                           "(negative ttl in effect)" % name)
            return False
        self.function_cache_time = time.time()
        for connection in self.gearman.active_connections:
            try:
                req = gear.StatusAdminRequest()
                connection.sendAdminRequest(req, timeout=300)
            except Exception:
                self.log.exception("Exception while checking functions")
                continue
            for line in req.response.split('\n'):
                parts = [x.strip() for x in line.split()]
                if not parts or parts[0] == '.':
                    continue
                self.function_cache.add(parts[0])
        if name in self.function_cache:
            self.log.debug("Function %s is registered" % name)
            return True
        self.log.debug("Function %s is not registered" % name)
        return False

    def execute(self, job, item, pipeline, dependent_items=[]):
        tenant = pipeline.layout.tenant
        uuid = str(uuid4().hex)
        self.log.info(
            "Execute job %s (uuid: %s) on nodes %s for change %s "
            "with dependent changes %s" % (
                job, uuid,
                item.current_build_set.getJobNodeSet(job.name),
                item.change,
                [x.change for x in dependent_items]))
        dependent_items = dependent_items[:]
        dependent_items.reverse()
        # TODOv3(jeblair): This ansible vars data structure will
        # replace the environment variables below.
        project = dict(
            name=item.change.project.name,
            canonical_hostname=item.change.project.canonical_hostname,
            canonical_name=item.change.project.canonical_name)

        zuul_params = dict(uuid=uuid,
                           pipeline=pipeline.name,
                           job=job.name,
                           project=project,
                           tags=' '.join(sorted(job.tags)))

        if hasattr(item.change, 'branch'):
            zuul_params['branch'] = item.change.branch
        if hasattr(item.change, 'number'):
            zuul_params['change'] = item.change.number
        if hasattr(item.change, 'patchset'):
            zuul_params['patchset'] = item.change.patchset
        # Legacy environment variables
        params = dict(ZUUL_UUID=uuid,
                      ZUUL_PROJECT=item.change.project.name)
        params['ZUUL_PIPELINE'] = pipeline.name
        params['ZUUL_URL'] = item.current_build_set.zuul_url
        params['ZUUL_VOTING'] = job.voting and '1' or '0'
        if hasattr(item.change, 'refspec'):
            changes_str = '^'.join(
                ['%s:%s:%s' % (i.change.project.name, i.change.branch,
                               i.change.refspec)
                 for i in dependent_items + [item]])
            params['ZUUL_BRANCH'] = item.change.branch
            params['ZUUL_CHANGES'] = changes_str
            params['ZUUL_REF'] = ('refs/zuul/%s/%s' %
                                  (item.change.branch,
                                   item.current_build_set.ref))
            params['ZUUL_COMMIT'] = item.current_build_set.commit

            zuul_changes = ' '.join(['%s,%s' % (i.change.number,
                                                i.change.patchset)
                                     for i in dependent_items + [item]])
            params['ZUUL_CHANGE_IDS'] = zuul_changes
            params['ZUUL_CHANGE'] = str(item.change.number)
            params['ZUUL_PATCHSET'] = str(item.change.patchset)
        if hasattr(item.change, 'ref') and item.change.ref is not None:
            params['ZUUL_REFNAME'] = item.change.ref
            params['ZUUL_OLDREV'] = item.change.oldrev
            params['ZUUL_NEWREV'] = item.change.newrev

            params['ZUUL_REF'] = item.change.ref
            params['ZUUL_COMMIT'] = item.change.newrev

        # This is what we should be heading toward for parameters:

        # required:
        # ZUUL_UUID
        # ZUUL_REF (/refs/zuul/..., /refs/tags/foo, master)
        # ZUUL_COMMIT

        # optional:
        # ZUUL_PROJECT
        # ZUUL_PIPELINE

        # optional (changes only):
        # ZUUL_BRANCH
        # ZUUL_CHANGE
        # ZUUL_CHANGE_IDS
        # ZUUL_PATCHSET

        # optional (ref updated only):
        # ZUUL_OLDREV
        # ZUUL_NEWREV

        all_items = dependent_items + [item]
        merger_items = [i.makeMergerItem() for i in all_items]

        params['job'] = job.name
        params['timeout'] = job.timeout
        params['items'] = merger_items
        params['projects'] = []

        if job.name != 'noop':
            params['playbooks'] = [x.toDict() for x in job.run]
            params['pre_playbooks'] = [x.toDict() for x in job.pre_run]
            params['post_playbooks'] = [x.toDict() for x in job.post_run]
            params['roles'] = [x.toDict() for x in job.roles]

        nodes = []
        for node in item.current_build_set.getJobNodeSet(job.name).getNodes():
            nodes.append(dict(name=node.name, image=node.image,
                              az=node.az,
                              host_keys=node.host_keys,
                              provider=node.provider,
                              region=node.region,
                              interface_ip=node.interface_ip,
                              public_ipv6=node.public_ipv6,
                              public_ipv4=node.public_ipv4))
        params['nodes'] = nodes
        params['vars'] = copy.deepcopy(job.variables)
        if job.auth:
            for secret in job.auth.secrets:
                params['vars'][secret.name] = copy.deepcopy(secret.secret_data)
        params['vars']['zuul'] = zuul_params
        projects = set()
        if job.repos:
            for repo in job.repos:
                (trusted, project) = tenant.getProject(repo)
                connection = project.source.connection
                params['projects'].append(
                    dict(connection=connection.connection_name,
                         name=project.name))
                projects.add(project)
        for item in all_items:
            if item.change.project not in projects:
                project = item.change.project
                connection = item.change.project.source.connection
                params['projects'].append(
                    dict(connection=connection.connection_name,
                         name=project.name))
                projects.add(project)

        build = Build(job, uuid)
        build.parameters = params

        if job.name == 'noop':
            self.sched.onBuildCompleted(build, 'SUCCESS')
            return build

        gearman_job = gear.TextJob('executor:execute', json.dumps(params),
                                   unique=uuid)
        build.__gearman_job = gearman_job
        build.__gearman_manager = None
        self.builds[uuid] = build

        # NOTE(pabelanger): Rather then looping forever, check to see if job
        # has passed attempts limit.
        if item.current_build_set.getTries(job.name) > job.attempts:
            self.onBuildCompleted(gearman_job, 'RETRY_LIMIT')
            return build

        if pipeline.precedence == zuul.model.PRECEDENCE_NORMAL:
            precedence = gear.PRECEDENCE_NORMAL
        elif pipeline.precedence == zuul.model.PRECEDENCE_HIGH:
            precedence = gear.PRECEDENCE_HIGH
        elif pipeline.precedence == zuul.model.PRECEDENCE_LOW:
            precedence = gear.PRECEDENCE_LOW

        try:
            self.gearman.submitJob(gearman_job, precedence=precedence,
                                   timeout=300)
        except Exception:
            self.log.exception("Unable to submit job to Gearman")
            self.onBuildCompleted(gearman_job, 'EXCEPTION')
            return build

        if not gearman_job.handle:
            self.log.error("No job handle was received for %s after"
                           " 300 seconds; marking as lost." %
                           gearman_job)
            self.onBuildCompleted(gearman_job, 'NO_HANDLE')

        self.log.debug("Received handle %s for %s" % (gearman_job.handle,
                                                      build))

        return build

    def cancel(self, build):
        # Returns whether a running build was canceled
        self.log.info("Cancel build %s for job %s" % (build, build.job))

        build.canceled = True
        try:
            job = build.__gearman_job  # noqa
        except AttributeError:
            self.log.debug("Build %s has no associated gearman job" % build)
            return False

        # TODOv3(jeblair): make a nicer way of recording build start.
        if build.url is not None:
            self.log.debug("Build %s has already started" % build)
            self.cancelRunningBuild(build)
            self.log.debug("Canceled running build %s" % build)
            return True
        else:
            self.log.debug("Build %s has not started yet" % build)

        self.log.debug("Looking for build %s in queue" % build)
        if self.cancelJobInQueue(build):
            self.log.debug("Removed build %s from queue" % build)
            return False

        time.sleep(1)

        self.log.debug("Still unable to find build %s to cancel" % build)
        if build.url:
            self.log.debug("Build %s has just started" % build)
            self.log.debug("Canceled running build %s" % build)
            self.cancelRunningBuild(build)
            return True
        self.log.debug("Unable to cancel build %s" % build)

    def onBuildCompleted(self, job, result=None):
        if job.unique in self.meta_jobs:
            del self.meta_jobs[job.unique]
            return

        build = self.builds.get(job.unique)
        if build:
            data = getJobData(job)
            build.node_labels = data.get('node_labels', [])
            build.node_name = data.get('node_name')
            if result is None:
                result = data.get('result')
            if result is None:
                build.retry = True
            self.log.info("Build %s complete, result %s" %
                          (job, result))
            self.sched.onBuildCompleted(build, result)
            # The test suite expects the build to be removed from the
            # internal dict after it's added to the report queue.
            del self.builds[job.unique]
        else:
            if not job.name.startswith("executor:stop:"):
                self.log.error("Unable to find build %s" % job.unique)

    def onWorkStatus(self, job):
        data = getJobData(job)
        self.log.debug("Build %s update %s" % (job, data))
        build = self.builds.get(job.unique)
        if build:
            started = (build.url is not None)
            # Allow URL to be updated
            build.url = data.get('url', build.url)
            # Update information about worker
            build.worker.updateFromData(data)

            if not started:
                self.log.info("Build %s started" % job)
                build.__gearman_manager = data.get('manager')
                self.sched.onBuildStarted(build)
        else:
            self.log.error("Unable to find build %s" % job.unique)

    def onDisconnect(self, job):
        self.log.info("Gearman job %s lost due to disconnect" % job)
        self.onBuildCompleted(job)

    def onUnknownJob(self, job):
        self.log.info("Gearman job %s lost due to unknown handle" % job)
        self.onBuildCompleted(job, 'LOST')

    def cancelJobInQueue(self, build):
        job = build.__gearman_job

        req = gear.CancelJobAdminRequest(job.handle)
        job.connection.sendAdminRequest(req, timeout=300)
        self.log.debug("Response to cancel build %s request: %s" %
                       (build, req.response.strip()))
        if req.response.startswith(b"OK"):
            try:
                del self.builds[job.unique]
            except:
                pass
            return True
        return False

    def cancelRunningBuild(self, build):
        if not build.__gearman_manager:
            self.log.error("Build %s has no manager while canceling" %
                           (build,))
        stop_uuid = str(uuid4().hex)
        data = dict(uuid=build.__gearman_job.unique)
        stop_job = gear.TextJob("executor:stop:%s" % build.__gearman_manager,
                                json.dumps(data), unique=stop_uuid)
        self.meta_jobs[stop_uuid] = stop_job
        self.log.debug("Submitting stop job: %s", stop_job)
        self.gearman.submitJob(stop_job, precedence=gear.PRECEDENCE_HIGH,
                               timeout=300)
        return True

    def lookForLostBuilds(self):
        self.log.debug("Looking for lost builds")
        for build in self.builds.values():
            if build.result:
                # The build has finished, it will be removed
                continue
            job = build.__gearman_job
            if not job.handle:
                # The build hasn't been enqueued yet
                continue
            p = gear.Packet(gear.constants.REQ, gear.constants.GET_STATUS,
                            job.handle)
            job.connection.sendPacket(p)
