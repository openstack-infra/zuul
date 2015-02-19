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

import gear
import inspect
import json
import logging
import os
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
        super(ZuulGearmanClient, self).__init__()
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

    def waitForGearmanToSettle(self):
        # If we're running the internal gearman server, it's possible
        # that after a restart or reload, we may be immediately ready
        # to run jobs but all the gearman workers may not have
        # registered yet.  Give them a sporting chance to show up
        # before we start declaring jobs lost because we don't have
        # gearman functions registered for them.

        # Spend up to 30 seconds after we connect to the gearman
        # server waiting for the set of defined jobs to become
        # consistent over a sliding 5 second window.

        self.log.info("Waiting for connection to internal Gearman server")
        self.waitForServer()
        self.log.info("Waiting for gearman function set to settle")
        start = time.time()
        last_change = start
        all_functions = set()
        while time.time() - start < 30:
            now = time.time()
            last_functions = set()
            for connection in self.active_connections:
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
                    last_functions.add(parts[0])
            if last_functions != all_functions:
                last_change = now
                all_functions.update(last_functions)
            else:
                if now - last_change > 5:
                    self.log.info("Gearman function set has settled")
                    break
            time.sleep(1)
        self.log.info("Done waiting for Gearman server")


class Gearman(object):
    log = logging.getLogger("zuul.Gearman")
    negative_function_cache_ttl = 5

    def __init__(self, config, sched, swift):
        self.config = config
        self.sched = sched
        self.swift = swift
        self.builds = {}
        self.meta_jobs = {}  # A list of meta-jobs like stop or describe

        server = config.get('gearman', 'server')
        if config.has_option('gearman', 'port'):
            port = config.get('gearman', 'port')
        else:
            port = 4730

        self.gearman = ZuulGearmanClient(self)
        self.gearman.addServer(server, port)

        if (config.has_option('gearman_server', 'start') and
            config.getboolean('gearman_server', 'start')):
            self.gearman.waitForGearmanToSettle()

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

    def updateBuildParams(self, job, item, params):
        """Allow the job to modify and add build parameters"""

        # NOTE(jhesketh): The params need to stay in a key=value data pair
        # as workers cannot necessarily handle lists.

        if job.swift and self.swift.connection:

            for name, s in job.swift.items():
                swift_instructions = {}
                s_config = {}
                s_config.update((k, v.format(item=item, job=job,
                                             change=item.change))
                                if isinstance(v, basestring)
                                else (k, v)
                                for k, v in s.items())

                (swift_instructions['URL'],
                 swift_instructions['HMAC_BODY'],
                 swift_instructions['SIGNATURE']) = \
                    self.swift.generate_form_post_middleware_params(
                        params['LOG_PATH'], **s_config)

                if 'logserver_prefix' in s_config:
                    swift_instructions['LOGSERVER_PREFIX'] = \
                        s_config['logserver_prefix']
                elif self.config.has_option('swift',
                                            'default_logserver_prefix'):
                    swift_instructions['LOGSERVER_PREFIX'] = \
                        self.config.get('swift', 'default_logserver_prefix')

                # Create a set of zuul instructions for each instruction-set
                # given  in the form of NAME_PARAMETER=VALUE
                for key, value in swift_instructions.items():
                    params['_'.join(['SWIFT', name, key])] = value

        if callable(job.parameter_function):
            pargs = inspect.getargspec(job.parameter_function)
            if len(pargs.args) == 2:
                job.parameter_function(item, params)
            else:
                job.parameter_function(item, job, params)
            self.log.debug("Custom parameter function used for job %s, "
                           "change: %s, params: %s" % (job, item.change,
                                                       params))

    def launch(self, job, item, pipeline, dependent_items=[]):
        self.log.info("Launch job %s for change %s with dependent changes %s" %
                      (job, item.change,
                       [x.change for x in dependent_items]))
        dependent_items = dependent_items[:]
        dependent_items.reverse()
        uuid = str(uuid4().hex)
        params = dict(ZUUL_UUID=uuid,
                      ZUUL_PROJECT=item.change.project.name)
        params['ZUUL_PIPELINE'] = pipeline.name
        params['ZUUL_URL'] = item.current_build_set.zuul_url
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
        if hasattr(item.change, 'ref'):
            params['ZUUL_REFNAME'] = item.change.ref
            params['ZUUL_OLDREV'] = item.change.oldrev
            params['ZUUL_NEWREV'] = item.change.newrev

            params['ZUUL_REF'] = item.change.ref
            params['ZUUL_COMMIT'] = item.change.newrev

        # The destination_path is a unqiue path for this build request
        # and generally where the logs are expected to be placed
        destination_path = os.path.join(item.change.getBasePath(),
                                        pipeline.name, job.name, uuid[:7])
        params['BASE_LOG_PATH'] = item.change.getBasePath()
        params['LOG_PATH'] = destination_path

        # Allow the job to update the params
        self.updateBuildParams(job, item, params)

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

        if 'ZUUL_NODE' in params:
            name = "build:%s:%s" % (job.name, params['ZUUL_NODE'])
        else:
            name = "build:%s" % job.name
        build = Build(job, uuid)
        build.parameters = params

        if job.name == 'noop':
            build.result = 'SUCCESS'
            self.sched.onBuildCompleted(build)
            return build

        gearman_job = gear.Job(name, json.dumps(params),
                               unique=uuid)
        build.__gearman_job = gearman_job
        self.builds[uuid] = build

        if not self.isJobRegistered(gearman_job.name):
            self.log.error("Job %s is not registered with Gearman" %
                           gearman_job)
            self.onBuildCompleted(gearman_job, 'NOT_REGISTERED')
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
        self.log.info("Cancel build %s for job %s" % (build, build.job))

        build.canceled = True
        try:
            job = build.__gearman_job  # noqa
        except AttributeError:
            self.log.debug("Build %s has no associated gearman job" % build)
            return

        if build.number is not None:
            self.log.debug("Build %s has already started" % build)
            self.cancelRunningBuild(build)
            self.log.debug("Canceled running build %s" % build)
            return
        else:
            self.log.debug("Build %s has not started yet" % build)

        self.log.debug("Looking for build %s in queue" % build)
        if self.cancelJobInQueue(build):
            self.log.debug("Removed build %s from queue" % build)
            return

        self.log.debug("Still unable to find build %s to cancel" % build)
        if build.number:
            self.log.debug("Build %s has just started" % build)
        else:
            self.log.error("Build %s has not started but was not"
                           "found in queue; canceling anyway" % build)
        self.cancelRunningBuild(build)
        self.log.debug("Canceled possibly running build %s" % build)

    def onBuildCompleted(self, job, result=None):
        if job.unique in self.meta_jobs:
            del self.meta_jobs[job.unique]
            return

        build = self.builds.get(job.unique)
        if build:
            if not build.canceled:
                if result is None:
                    data = getJobData(job)
                    result = data.get('result')
                if result is None:
                    build.retry = True
                self.log.info("Build %s complete, result %s" %
                              (job, result))
                build.result = result
                self.sched.onBuildCompleted(build)
            # The test suite expects the build to be removed from the
            # internal dict after it's added to the report queue.
            del self.builds[job.unique]
        else:
            if not job.name.startswith("stop:"):
                self.log.error("Unable to find build %s" % job.unique)

    def onWorkStatus(self, job):
        data = getJobData(job)
        self.log.debug("Build %s update %s" % (job, data))
        build = self.builds.get(job.unique)
        if build:
            # Allow URL to be updated
            build.url = data.get('url') or build.url
            # Update information about worker
            build.worker.updateFromData(data)

            if build.number is None:
                self.log.info("Build %s started" % job)
                build.number = data.get('number')
                build.__gearman_manager = data.get('manager')
                self.sched.onBuildStarted(build)

            if job.denominator:
                build.estimated_time = float(job.denominator) / 1000
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
        if req.response.startswith("OK"):
            try:
                del self.builds[job.unique]
            except:
                pass
            return True
        return False

    def cancelRunningBuild(self, build):
        stop_uuid = str(uuid4().hex)
        data = dict(name=build.job.name,
                    number=build.number)
        stop_job = gear.Job("stop:%s" % build.__gearman_manager,
                            json.dumps(data), unique=stop_uuid)
        self.meta_jobs[stop_uuid] = stop_job
        self.log.debug("Submitting stop job: %s", stop_job)
        self.gearman.submitJob(stop_job, precedence=gear.PRECEDENCE_HIGH,
                               timeout=300)
        return True

    def setBuildDescription(self, build, desc):
        try:
            name = "set_description:%s" % build.__gearman_manager
        except AttributeError:
            # We haven't yet received the first data packet that tells
            # us where the job is running.
            return False

        if not self.isJobRegistered(name):
            return False

        desc_uuid = str(uuid4().hex)
        data = dict(name=build.job.name,
                    number=build.number,
                    html_description=desc)
        desc_job = gear.Job(name, json.dumps(data), unique=desc_uuid)
        self.meta_jobs[desc_uuid] = desc_job
        self.log.debug("Submitting describe job: %s", desc_job)
        self.gearman.submitJob(desc_job, precedence=gear.PRECEDENCE_LOW,
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
