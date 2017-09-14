# Copyright 2012-2015 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
# Copyright 2013 Antoine "hashar" Musso
# Copyright 2013 Wikimedia Foundation Inc.
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
import os
import pickle
import queue
import socket
import sys
import threading
import time

from zuul import configloader
from zuul import model
from zuul import exceptions
from zuul import version as zuul_version
from zuul import rpclistener
from zuul.lib import commandsocket
from zuul.lib.config import get_default
from zuul.lib.statsd import get_statsd
import zuul.lib.queue

COMMANDS = ['stop']


class ManagementEvent(object):
    """An event that should be processed within the main queue run loop"""
    def __init__(self):
        self._wait_event = threading.Event()
        self._exc_info = None

    def exception(self, exc_info):
        self._exc_info = exc_info
        self._wait_event.set()

    def done(self):
        self._wait_event.set()

    def wait(self, timeout=None):
        self._wait_event.wait(timeout)
        if self._exc_info:
            # sys.exc_info returns (type, value, traceback)
            type_, exception_instance, traceback = self._exc_info
            raise exception_instance.with_traceback(traceback)
        return self._wait_event.is_set()


class ReconfigureEvent(ManagementEvent):
    """Reconfigure the scheduler.  The layout will be (re-)loaded from
    the path specified in the configuration.

    :arg ConfigParser config: the new configuration
    """
    def __init__(self, config):
        super(ReconfigureEvent, self).__init__()
        self.config = config


class TenantReconfigureEvent(ManagementEvent):
    """Reconfigure the given tenant.  The layout will be (re-)loaded from
    the path specified in the configuration.

    :arg Tenant tenant: the tenant to reconfigure
    :arg Project project: if supplied, clear the cached configuration
         from this project first
    """
    def __init__(self, tenant, project):
        super(TenantReconfigureEvent, self).__init__()
        self.tenant_name = tenant.name
        self.projects = set([project])

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, TenantReconfigureEvent):
            return False
        # We don't check projects because they will get combined when
        # merged.
        return (self.tenant_name == other.tenant_name)

    def merge(self, other):
        if self.tenant_name != other.tenant_name:
            raise Exception("Can not merge events from different tenants")
        self.projects |= other.projects


class PromoteEvent(ManagementEvent):
    """Promote one or more changes to the head of the queue.

    :arg str tenant_name: the name of the tenant
    :arg str pipeline_name: the name of the pipeline
    :arg list change_ids: a list of strings of change ids in the form
        1234,1
    """

    def __init__(self, tenant_name, pipeline_name, change_ids):
        super(PromoteEvent, self).__init__()
        self.tenant_name = tenant_name
        self.pipeline_name = pipeline_name
        self.change_ids = change_ids


class EnqueueEvent(ManagementEvent):
    """Enqueue a change into a pipeline

    :arg TriggerEvent trigger_event: a TriggerEvent describing the
        trigger, pipeline, and change to enqueue
    """

    def __init__(self, trigger_event):
        super(EnqueueEvent, self).__init__()
        self.trigger_event = trigger_event


class ResultEvent(object):
    """An event that needs to modify the pipeline state due to a
    result from an external system."""

    pass


class BuildStartedEvent(ResultEvent):
    """A build has started.

    :arg Build build: The build which has started.
    """

    def __init__(self, build):
        self.build = build


class BuildCompletedEvent(ResultEvent):
    """A build has completed

    :arg Build build: The build which has completed.
    """

    def __init__(self, build):
        self.build = build


class MergeCompletedEvent(ResultEvent):
    """A remote merge operation has completed

    :arg BuildSet build_set: The build_set which is ready.
    :arg bool merged: Whether the merge succeeded (changes with refs).
    :arg bool updated: Whether the repo was updated (changes without refs).
    :arg str commit: The SHA of the merged commit (changes with refs).
    :arg dict repo_state: The starting repo state before the merge.
    """

    def __init__(self, build_set, merged, updated, commit,
                 files, repo_state):
        self.build_set = build_set
        self.merged = merged
        self.updated = updated
        self.commit = commit
        self.files = files
        self.repo_state = repo_state


class NodesProvisionedEvent(ResultEvent):
    """Nodes have been provisioned for a build_set

    :arg BuildSet build_set: The build_set which has nodes.
    :arg list of Node objects nodes: The provisioned nodes
    """

    def __init__(self, request):
        self.request = request
        self.request_id = request.id


class Scheduler(threading.Thread):
    """The engine of Zuul.

    The Scheduler is reponsible for recieving events and dispatching
    them to appropriate components (including pipeline managers,
    mergers and executors).

    It runs a single threaded main loop which processes events
    received one at a time and takes action as appropriate.  Other
    parts of Zuul may run in their own thread, but synchronization is
    performed within the scheduler to reduce or eliminate the need for
    locking in most circumstances.

    The main daemon will have one instance of the Scheduler class
    running which will persist for the life of the process.  The
    Scheduler instance is supplied to other Zuul components so that
    they can submit events or otherwise communicate with other
    components.

    """

    log = logging.getLogger("zuul.Scheduler")
    _stats_interval = 30

    def __init__(self, config, testonly=False):
        threading.Thread.__init__(self)
        self.daemon = True
        self.hostname = socket.gethostname()
        self.wake_event = threading.Event()
        self.layout_lock = threading.Lock()
        self.run_handler_lock = threading.Lock()
        self.command_map = dict(
            stop=self.stop,
        )
        self._pause = False
        self._exit = False
        self._stopped = False
        self.executor = None
        self.merger = None
        self.connections = None
        self.statsd = get_statsd(config)
        self.rpc = rpclistener.RPCListener(config, self)
        self.stats_thread = threading.Thread(target=self.runStats)
        self.stats_stop = threading.Event()
        # TODO(jeblair): fix this
        # Despite triggers being part of the pipeline, there is one trigger set
        # per scheduler. The pipeline handles the trigger filters but since
        # the events are handled by the scheduler itself it needs to handle
        # the loading of the triggers.
        # self.triggers['connection_name'] = triggerObject
        self.triggers = dict()
        self.config = config

        self.trigger_event_queue = queue.Queue()
        self.result_event_queue = queue.Queue()
        self.management_event_queue = zuul.lib.queue.MergedQueue()
        self.abide = model.Abide()

        if not testonly:
            time_dir = self._get_time_database_dir()
            self.time_database = model.TimeDataBase(time_dir)

        command_socket = get_default(
            self.config, 'scheduler', 'command_socket',
            '/var/lib/zuul/scheduler.socket')
        self.command_socket = commandsocket.CommandSocket(command_socket)

        self.zuul_version = zuul_version.version_info.release_string()
        self.last_reconfigured = None
        self.tenant_last_reconfigured = {}
        self.autohold_requests = {}

    def start(self):
        super(Scheduler, self).start()
        self._command_running = True
        self.log.debug("Starting command processor")
        self.command_socket.start()
        self.command_thread = threading.Thread(target=self.runCommand,
                                               name='command')
        self.command_thread.daemon = True
        self.command_thread.start()

        self.rpc.start()
        self.stats_thread.start()

    def stop(self):
        self._stopped = True
        self.stats_stop.set()
        self.stopConnections()
        self.wake_event.set()
        self.stats_thread.join()
        self.rpc.stop()
        self.rpc.join()
        self._command_running = False
        self.command_socket.stop()

    def runCommand(self):
        while self._command_running:
            try:
                command = self.command_socket.get().decode('utf8')
                if command != '_stop':
                    self.command_map[command]()
            except Exception:
                self.log.exception("Exception while processing command")

    def registerConnections(self, connections, load=True):
        # load: whether or not to trigger the onLoad for the connection. This
        # is useful for not doing a full load during layout validation.
        self.connections = connections
        self.connections.registerScheduler(self, load)

    def stopConnections(self):
        self.connections.stop()

    def setExecutor(self, executor):
        self.executor = executor

    def setMerger(self, merger):
        self.merger = merger

    def setNodepool(self, nodepool):
        self.nodepool = nodepool

    def setZooKeeper(self, zk):
        self.zk = zk

    def runStats(self):
        while not self.stats_stop.wait(self._stats_interval):
            try:
                self._runStats()
            except Exception:
                self.log.exception("Error in periodic stats:")

    def _runStats(self):
        if not self.statsd:
            return
        functions = self.rpc.getFunctions()
        executors_accepting = 0
        executors_online = 0
        execute_queue = 0
        execute_running = 0
        mergers_online = 0
        merge_queue = 0
        merge_running = 0
        for (name, (queued, running, registered)) in functions.items():
            if name == 'executor:execute':
                executors_accepting = registered
                execute_queue = queued - running
                execute_running = running
            if name.startswith('executor:stop'):
                executors_online += registered
            if name == 'merger:merge':
                mergers_online = registered
            if name.startswith('merger:'):
                merge_queue += queued - running
                merge_running += running
        self.statsd.gauge('zuul.mergers.online', mergers_online)
        self.statsd.gauge('zuul.mergers.jobs_running', merge_running)
        self.statsd.gauge('zuul.mergers.jobs_queued', merge_queue)
        self.statsd.gauge('zuul.executors.online', executors_online)
        self.statsd.gauge('zuul.executors.accepting', executors_accepting)
        self.statsd.gauge('zuul.executors.jobs_running', execute_running)
        self.statsd.gauge('zuul.executors.jobs_queued', execute_queue)

    def addEvent(self, event):
        self.trigger_event_queue.put(event)
        self.wake_event.set()

    def onBuildStarted(self, build):
        build.start_time = time.time()
        event = BuildStartedEvent(build)
        self.result_event_queue.put(event)
        self.wake_event.set()

    def onBuildCompleted(self, build, result, result_data):
        build.end_time = time.time()
        build.result_data = result_data
        # Note, as soon as the result is set, other threads may act
        # upon this, even though the event hasn't been fully
        # processed.  Ensure that any other data from the event (eg,
        # timing) is recorded before setting the result.
        build.result = result
        try:
            if self.statsd and build.pipeline:
                tenant = build.pipeline.layout.tenant
                jobname = build.job.name.replace('.', '_').replace('/', '_')
                hostname = (build.build_set.item.change.project.
                            canonical_hostname.replace('.', '_'))
                projectname = (build.build_set.item.change.project.name.
                               replace('.', '_').replace('/', '_'))
                branchname = (build.build_set.item.change.branch.
                              replace('.', '_').replace('/', '_'))
                basekey = 'zuul.tenant.%s' % tenant.name
                pipekey = '%s.pipeline.%s' % (basekey, build.pipeline.name)
                # zuul.tenant.<tenant>.pipeline.<pipeline>.all_jobs
                key = '%s.all_jobs' % pipekey
                self.statsd.incr(key)
                jobkey = '%s.project.%s.%s.%s.job.%s' % (
                    pipekey, hostname, projectname, branchname, jobname)
                # zuul.tenant.<tenant>.pipeline.<pipeline>.project.
                #   <host>.<project>.<branch>.job.<job>.<result>
                key = '%s.%s' % (jobkey, build.result)
                if build.result in ['SUCCESS', 'FAILURE'] and build.start_time:
                    dt = int((build.end_time - build.start_time) * 1000)
                    self.statsd.timing(key, dt)
                self.statsd.incr(key)
                # zuul.tenant.<tenant>.pipeline.<pipeline>.project.
                #  <host>.<project>.<branch>.job.<job>.wait_time
                if build.start_time:
                    key = '%s.wait_time' % jobkey
                    dt = int((build.start_time - build.execute_time) * 1000)
                    self.statsd.timing(key, dt)
        except Exception:
            self.log.exception("Exception reporting runtime stats")
        event = BuildCompletedEvent(build)
        self.result_event_queue.put(event)
        self.wake_event.set()

    def onMergeCompleted(self, build_set, merged, updated,
                         commit, files, repo_state):
        event = MergeCompletedEvent(build_set, merged,
                                    updated, commit, files, repo_state)
        self.result_event_queue.put(event)
        self.wake_event.set()

    def onNodesProvisioned(self, req):
        event = NodesProvisionedEvent(req)
        self.result_event_queue.put(event)
        self.wake_event.set()

    def reconfigureTenant(self, tenant, project):
        self.log.debug("Submitting tenant reconfiguration event for "
                       "%s due to project %s", tenant.name, project)
        event = TenantReconfigureEvent(tenant, project)
        self.management_event_queue.put(event)
        self.wake_event.set()

    def reconfigure(self, config):
        self.log.debug("Submitting reconfiguration event")
        event = ReconfigureEvent(config)
        self.management_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Waiting for reconfiguration")
        event.wait()
        self.log.debug("Reconfiguration complete")
        self.last_reconfigured = int(time.time())
        # TODOv3(jeblair): reconfigure time should be per-tenant

    def autohold(self, tenant_name, project_name, job_name, reason, count):
        key = (tenant_name, project_name, job_name)
        if count == 0 and key in self.autohold_requests:
            self.log.debug("Removing autohold for %s", key)
            del self.autohold_requests[key]
        else:
            self.log.debug("Autohold requested for %s", key)
            self.autohold_requests[key] = (count, reason)

    def promote(self, tenant_name, pipeline_name, change_ids):
        event = PromoteEvent(tenant_name, pipeline_name, change_ids)
        self.management_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Waiting for promotion")
        event.wait()
        self.log.debug("Promotion complete")

    def enqueue(self, trigger_event):
        event = EnqueueEvent(trigger_event)
        self.management_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Waiting for enqueue")
        event.wait()
        self.log.debug("Enqueue complete")

    def exit(self):
        self.log.debug("Prepare to exit")
        self._pause = True
        self._exit = True
        self.wake_event.set()
        self.log.debug("Waiting for exit")

    def _get_queue_pickle_file(self):
        state_dir = get_default(self.config, 'scheduler', 'state_dir',
                                '/var/lib/zuul', expand_user=True)
        return os.path.join(state_dir, 'queue.pickle')

    def _get_time_database_dir(self):
        state_dir = get_default(self.config, 'scheduler', 'state_dir',
                                '/var/lib/zuul', expand_user=True)
        d = os.path.join(state_dir, 'times')
        if not os.path.exists(d):
            os.mkdir(d)
        return d

    def _get_project_key_dir(self):
        state_dir = get_default(self.config, 'scheduler', 'state_dir',
                                '/var/lib/zuul', expand_user=True)
        key_dir = os.path.join(state_dir, 'keys')
        if not os.path.exists(key_dir):
            os.mkdir(key_dir, 0o700)
        st = os.stat(key_dir)
        mode = st.st_mode & 0o777
        if mode != 0o700:
            raise Exception("Project key directory %s must be mode 0700; "
                            "current mode is %o" % (key_dir, mode))
        return key_dir

    def _save_queue(self):
        pickle_file = self._get_queue_pickle_file()
        events = []
        while not self.trigger_event_queue.empty():
            events.append(self.trigger_event_queue.get())
        self.log.debug("Queue length is %s" % len(events))
        if events:
            self.log.debug("Saving queue")
            pickle.dump(events, open(pickle_file, 'wb'))

    def _load_queue(self):
        pickle_file = self._get_queue_pickle_file()
        if os.path.exists(pickle_file):
            self.log.debug("Loading queue")
            events = pickle.load(open(pickle_file, 'rb'))
            self.log.debug("Queue length is %s" % len(events))
            for event in events:
                self.trigger_event_queue.put(event)
        else:
            self.log.debug("No queue file found")

    def _delete_queue(self):
        pickle_file = self._get_queue_pickle_file()
        if os.path.exists(pickle_file):
            self.log.debug("Deleting saved queue")
            os.unlink(pickle_file)

    def resume(self):
        try:
            self._load_queue()
        except Exception:
            self.log.exception("Unable to load queue")
        try:
            self._delete_queue()
        except Exception:
            self.log.exception("Unable to delete saved queue")
        self.log.debug("Resuming queue processing")
        self.wake_event.set()

    def _doPauseEvent(self):
        if self._exit:
            self.log.debug("Exiting")
            self._save_queue()
            os._exit(0)

    def _doReconfigureEvent(self, event):
        # This is called in the scheduler loop after another thread submits
        # a request
        self.layout_lock.acquire()
        self.config = event.config
        try:
            self.log.debug("Full reconfiguration beginning")
            loader = configloader.ConfigLoader()
            abide = loader.loadConfig(
                self.config.get('scheduler', 'tenant_config'),
                self._get_project_key_dir(),
                self, self.merger, self.connections)
            for tenant in abide.tenants.values():
                self._reconfigureTenant(tenant)
            self.abide = abide
        finally:
            self.layout_lock.release()
        self.log.debug("Full reconfiguration complete")

    def _doTenantReconfigureEvent(self, event):
        # This is called in the scheduler loop after another thread submits
        # a request
        self.layout_lock.acquire()
        try:
            self.log.debug("Tenant reconfiguration beginning")
            # If a change landed to a project, clear out the cached
            # config before reconfiguring.
            for project in event.projects:
                project.unparsed_config = None
            old_tenant = self.abide.tenants[event.tenant_name]
            loader = configloader.ConfigLoader()
            abide = loader.reloadTenant(
                self.config.get('scheduler', 'tenant_config'),
                self._get_project_key_dir(),
                self, self.merger, self.connections,
                self.abide, old_tenant)
            tenant = abide.tenants[event.tenant_name]
            self._reconfigureTenant(tenant)
            self.abide = abide
        finally:
            self.layout_lock.release()
        self.log.debug("Tenant reconfiguration complete")

    def _reenqueueGetProject(self, tenant, item):
        project = item.change.project
        # Attempt to get the same project as the one passed in.  If
        # the project is now found on a different connection, return
        # the new version of the project.  If it is no longer
        # available (due to a connection being removed), return None.
        (trusted, new_project) = tenant.getProject(project.canonical_name)
        if new_project:
            return new_project
        # If this is a non-live item we may be looking at a
        # "foreign" project, ie, one which is not defined in the
        # config but is constructed ad-hoc to satisfy a
        # cross-repo-dependency.  Find the corresponding live item
        # and use its source.
        child = item
        while child and not child.live:
            # This assumes that the queue does not branch behind this
            # item, which is currently true for non-live items; if
            # that changes, this traversal will need to be more
            # complex.
            if child.items_behind:
                child = child.items_behind[0]
            else:
                child = None
        if child is item:
            return None
        if child and child.live:
            (child_trusted, child_project) = tenant.getProject(
                child.change.project.canonical_name)
            if child_project:
                source = child_project.source
                new_project = source.getProject(project.name)
                return new_project
        return None

    def _reenqueueTenant(self, old_tenant, tenant):
        for name, new_pipeline in tenant.layout.pipelines.items():
            old_pipeline = old_tenant.layout.pipelines.get(name)
            if not old_pipeline:
                self.log.warning("No old pipeline matching %s found "
                                 "when reconfiguring" % name)
                continue
            self.log.debug("Re-enqueueing changes for pipeline %s" % name)
            # TODO(jeblair): This supports an undocument and
            # unanticipated hack to create a static window.  If we
            # really want to support this, maybe we should have a
            # 'static' type?  But it may be in use in the wild, so we
            # should allow this at least until there's an upgrade
            # path.
            if (new_pipeline.window and
                new_pipeline.window_increase_type == 'exponential' and
                new_pipeline.window_decrease_type == 'exponential' and
                new_pipeline.window_increase_factor == 1 and
                new_pipeline.window_decrease_factor == 1):
                static_window = True
            else:
                static_window = False
            if old_pipeline.window and (not static_window):
                new_pipeline.window = max(old_pipeline.window,
                                          new_pipeline.window_floor)
            items_to_remove = []
            builds_to_cancel = []
            last_head = None
            for shared_queue in old_pipeline.queues:
                # Attempt to keep window sizes from shrinking where possible
                new_queue = new_pipeline.getQueue(shared_queue.projects[0])
                if new_queue and shared_queue.window and (not static_window):
                    new_queue.window = max(shared_queue.window,
                                           new_queue.window_floor)
                for item in shared_queue.queue:
                    if not item.item_ahead:
                        last_head = item
                    item.pipeline = None
                    item.queue = None
                    item.change.project = self._reenqueueGetProject(
                        tenant, item)
                    # If the old item ahead made it in, re-enqueue
                    # this one behind it.
                    if item.item_ahead in items_to_remove:
                        old_item_ahead = None
                        item_ahead_valid = False
                    else:
                        old_item_ahead = item.item_ahead
                        item_ahead_valid = True
                    item.item_ahead = None
                    item.items_behind = []
                    reenqueued = False
                    if item.change.project:
                        try:
                            reenqueued = new_pipeline.manager.reEnqueueItem(
                                item, last_head, old_item_ahead,
                                item_ahead_valid=item_ahead_valid)
                        except Exception:
                            self.log.exception(
                                "Exception while re-enqueing item %s",
                                item)
                    if reenqueued:
                        for build in item.current_build_set.getBuilds():
                            new_job = item.getJob(build.job.name)
                            if new_job:
                                build.job = new_job
                            else:
                                item.removeBuild(build)
                                builds_to_cancel.append(build)
                    else:
                        items_to_remove.append(item)
            for item in items_to_remove:
                self.log.warning(
                    "Removing item %s during reconfiguration" % (item,))
                for build in item.current_build_set.getBuilds():
                    builds_to_cancel.append(build)
            for build in builds_to_cancel:
                self.log.warning(
                    "Canceling build %s during reconfiguration" % (build,))
                try:
                    self.executor.cancel(build)
                except Exception:
                    self.log.exception(
                        "Exception while canceling build %s "
                        "for change %s" % (build, build.build_set.item.change))
                # In the unlikely case that a build is removed and
                # later added back, make sure we clear out the nodeset
                # so it gets requested again.
                try:
                    build.build_set.removeJobNodeSet(build.job.name)
                except Exception:
                    self.log.exception(
                        "Exception while removing nodeset from build %s "
                        "for change %s" % (build, build.build_set.item.change))
                finally:
                    tenant.semaphore_handler.release(
                        build.build_set.item, build.job)

    def _reconfigureTenant(self, tenant):
        # This is called from _doReconfigureEvent while holding the
        # layout lock
        old_tenant = self.abide.tenants.get(tenant.name)

        if old_tenant:
            # Copy over semaphore handler so we don't loose the currently
            # held semaphores.
            tenant.semaphore_handler = old_tenant.semaphore_handler

            self._reenqueueTenant(old_tenant, tenant)

        # TODOv3(jeblair): update for tenants
        # self.maintainConnectionCache()
        self.connections.reconfigureDrivers(tenant)

        # TODOv3(jeblair): remove postconfig calls?
        for pipeline in tenant.layout.pipelines.values():
            for trigger in pipeline.triggers:
                trigger.postConfig(pipeline)
            for reporter in pipeline.actions:
                reporter.postConfig()
        self.tenant_last_reconfigured[tenant.name] = int(time.time())
        if self.statsd:
            try:
                for pipeline in tenant.layout.pipelines.values():
                    items = len(pipeline.getAllItems())
                    # stats.gauges.zuul.tenant.<tenant>.pipeline.
                    #    <pipeline>.current_changes
                    key = 'zuul.tenant.%s.pipeline.%s' % (
                        tenant.name, pipeline.name)
                    self.statsd.gauge(key + '.current_changes', items)
            except Exception:
                self.log.exception("Exception reporting initial "
                                   "pipeline stats:")

    def _doPromoteEvent(self, event):
        tenant = self.abide.tenants.get(event.tenant_name)
        pipeline = tenant.layout.pipelines[event.pipeline_name]
        change_ids = [c.split(',') for c in event.change_ids]
        items_to_enqueue = []
        change_queue = None
        for shared_queue in pipeline.queues:
            if change_queue:
                break
            for item in shared_queue.queue:
                if (item.change.number == change_ids[0][0] and
                        item.change.patchset == change_ids[0][1]):
                    change_queue = shared_queue
                    break
        if not change_queue:
            raise Exception("Unable to find shared change queue for %s" %
                            event.change_ids[0])
        for number, patchset in change_ids:
            found = False
            for item in change_queue.queue:
                if (item.change.number == number and
                        item.change.patchset == patchset):
                    found = True
                    items_to_enqueue.append(item)
                    break
            if not found:
                raise Exception("Unable to find %s,%s in queue %s" %
                                (number, patchset, change_queue))
        for item in change_queue.queue[:]:
            if item not in items_to_enqueue:
                items_to_enqueue.append(item)
            pipeline.manager.cancelJobs(item)
            pipeline.manager.dequeueItem(item)
        for item in items_to_enqueue:
            pipeline.manager.addChange(
                item.change,
                enqueue_time=item.enqueue_time,
                quiet=True,
                ignore_requirements=True)

    def _doEnqueueEvent(self, event):
        tenant = self.abide.tenants.get(event.tenant_name)
        (trusted, project) = tenant.getProject(event.project_name)
        pipeline = tenant.layout.pipelines[event.forced_pipeline]
        change = project.source.getChange(event, project)
        self.log.debug("Event %s for change %s was directly assigned "
                       "to pipeline %s" % (event, change, self))
        pipeline.manager.addChange(change, ignore_requirements=True)

    def _areAllBuildsComplete(self):
        self.log.debug("Checking if all builds are complete")
        if self.merger.areMergesOutstanding():
            self.log.debug("Waiting on merger")
            return False
        waiting = False
        for tenant in self.abide.tenants.values():
            for pipeline in tenant.layout.pipelines.values():
                for item in pipeline.getAllItems():
                    for build in item.current_build_set.getBuilds():
                        if build.result is None:
                            self.log.debug("%s waiting on %s" %
                                           (pipeline.manager, build))
                            waiting = True
        if not waiting:
            self.log.debug("All builds are complete")
            return True
        return False

    def run(self):
        if self.statsd:
            self.log.debug("Statsd enabled")
        else:
            self.log.debug("Statsd not configured")
        while True:
            self.log.debug("Run handler sleeping")
            self.wake_event.wait()
            self.wake_event.clear()
            if self._stopped:
                self.log.debug("Run handler stopping")
                return
            self.log.debug("Run handler awake")
            self.run_handler_lock.acquire()
            try:
                while not self.management_event_queue.empty():
                    self.process_management_queue()

                # Give result events priority -- they let us stop builds,
                # whereas trigger events cause us to execute builds.
                while not self.result_event_queue.empty():
                    self.process_result_queue()

                if not self._pause:
                    while not self.trigger_event_queue.empty():
                        self.process_event_queue()

                if self._pause and self._areAllBuildsComplete():
                    self._doPauseEvent()

                for tenant in self.abide.tenants.values():
                    for pipeline in tenant.layout.pipelines.values():
                        while pipeline.manager.processQueue():
                            pass

            except Exception:
                self.log.exception("Exception in run handler:")
                # There may still be more events to process
                self.wake_event.set()
            finally:
                self.run_handler_lock.release()

    def maintainConnectionCache(self):
        # TODOv3(jeblair): update for tenants
        relevant = set()
        for tenant in self.abide.tenants.values():
            for pipeline in tenant.layout.pipelines.values():
                self.log.debug("Gather relevant cache items for: %s" %
                               pipeline)

                for item in pipeline.getAllItems():
                    relevant.add(item.change)
                    relevant.update(item.change.getRelatedChanges())
        for connection in self.connections.values():
            connection.maintainCache(relevant)
            self.log.debug(
                "End maintain connection cache for: %s" % connection)
        self.log.debug("Connection cache size: %s" % len(relevant))

    def process_event_queue(self):
        self.log.debug("Fetching trigger event")
        event = self.trigger_event_queue.get()
        self.log.debug("Processing trigger event %s" % event)
        try:
            full_project_name = ('/'.join([event.project_hostname,
                                           event.project_name]))
            for tenant in self.abide.tenants.values():
                (trusted, project) = tenant.getProject(full_project_name)
                if project is None:
                    continue
                try:
                    change = project.source.getChange(event)
                except exceptions.ChangeNotFound as e:
                    self.log.debug("Unable to get change %s from "
                                   "source %s",
                                   e.change, project.source)
                    continue
                if ((event.branch_updated and
                     hasattr(change, 'files') and
                     change.updatesConfig()) or
                    event.branch_created or
                    event.branch_deleted):
                    # The change that just landed updates the config
                    # or a branch was just created or deleted.  Clear
                    # out cached data for this project and perform a
                    # reconfiguration.
                    self.reconfigureTenant(tenant, change.project)
                for pipeline in tenant.layout.pipelines.values():
                    if event.isPatchsetCreated():
                        pipeline.manager.removeOldVersionsOfChange(change)
                    elif event.isChangeAbandoned():
                        pipeline.manager.removeAbandonedChange(change)
                    if pipeline.manager.eventMatches(event, change):
                        pipeline.manager.addChange(change)
        finally:
            self.trigger_event_queue.task_done()

    def process_management_queue(self):
        self.log.debug("Fetching management event")
        event = self.management_event_queue.get()
        self.log.debug("Processing management event %s" % event)
        try:
            if isinstance(event, ReconfigureEvent):
                self._doReconfigureEvent(event)
            elif isinstance(event, TenantReconfigureEvent):
                self._doTenantReconfigureEvent(event)
            elif isinstance(event, PromoteEvent):
                self._doPromoteEvent(event)
            elif isinstance(event, EnqueueEvent):
                self._doEnqueueEvent(event.trigger_event)
            else:
                self.log.error("Unable to handle event %s" % event)
            event.done()
        except Exception:
            self.log.exception("Exception in management event:")
            event.exception(sys.exc_info())
        self.management_event_queue.task_done()

    def process_result_queue(self):
        self.log.debug("Fetching result event")
        event = self.result_event_queue.get()
        self.log.debug("Processing result event %s" % event)
        try:
            if isinstance(event, BuildStartedEvent):
                self._doBuildStartedEvent(event)
            elif isinstance(event, BuildCompletedEvent):
                self._doBuildCompletedEvent(event)
            elif isinstance(event, MergeCompletedEvent):
                self._doMergeCompletedEvent(event)
            elif isinstance(event, NodesProvisionedEvent):
                self._doNodesProvisionedEvent(event)
            else:
                self.log.error("Unable to handle event %s" % event)
        finally:
            self.result_event_queue.task_done()

    def _doBuildStartedEvent(self, event):
        build = event.build
        if build.build_set is not build.build_set.item.current_build_set:
            self.log.warning("Build %s is not in the current build set" %
                             (build,))
            return
        pipeline = build.build_set.item.pipeline
        if not pipeline:
            self.log.warning("Build %s is not associated with a pipeline" %
                             (build,))
            return
        try:
            build.estimated_time = float(self.time_database.getEstimatedTime(
                build))
        except Exception:
            self.log.exception("Exception estimating build time:")
        pipeline.manager.onBuildStarted(event.build)

    def _doBuildCompletedEvent(self, event):
        build = event.build

        # Regardless of any other conditions which might cause us not
        # to pass this on to the pipeline manager, make sure we return
        # the nodes to nodepool.
        try:
            nodeset = build.nodeset
            autohold_key = (build.pipeline.layout.tenant.name,
                            build.build_set.item.change.project.canonical_name,
                            build.job.name)
            if (build.result == "FAILURE" and
                autohold_key in self.autohold_requests):
                # We explicitly only want to hold nodes for jobs if they have
                # failed and have an autohold request.
                try:
                    self.nodepool.holdNodeSet(nodeset, autohold_key)
                except Exception:
                    self.log.exception("Unable to process autohold for %s:",
                                       autohold_key)
                    if autohold_key in self.autohold_requests:
                        self.log.debug("Removing autohold %s due to exception",
                                       autohold_key)
                        del self.autohold_requests[autohold_key]

            self.nodepool.returnNodeSet(nodeset)
        except Exception:
            self.log.exception("Unable to return nodeset %s" % (nodeset,))

        if build.build_set is not build.build_set.item.current_build_set:
            self.log.debug("Build %s is not in the current build set" %
                           (build,))
            return
        pipeline = build.build_set.item.pipeline
        if not pipeline:
            self.log.warning("Build %s is not associated with a pipeline" %
                             (build,))
            return
        if build.end_time and build.start_time and build.result:
            duration = build.end_time - build.start_time
            try:
                self.time_database.update(build, duration, build.result)
            except Exception:
                self.log.exception("Exception recording build time:")
        pipeline.manager.onBuildCompleted(event.build)

    def _doMergeCompletedEvent(self, event):
        build_set = event.build_set
        if build_set is not build_set.item.current_build_set:
            self.log.warning("Build set %s is not current" % (build_set,))
            return
        pipeline = build_set.item.pipeline
        if not pipeline:
            self.log.warning("Build set %s is not associated with a pipeline" %
                             (build_set,))
            return
        pipeline.manager.onMergeCompleted(event)

    def _doNodesProvisionedEvent(self, event):
        request = event.request
        request_id = event.request_id
        build_set = request.build_set

        self.nodepool.acceptNodes(request, request_id)
        if request.canceled:
            return

        if build_set is not build_set.item.current_build_set:
            self.log.warning("Build set %s is not current" % (build_set,))
            if request.fulfilled:
                self.nodepool.returnNodeSet(request.nodeset)
            return
        pipeline = build_set.item.pipeline
        if not pipeline:
            self.log.warning("Build set %s is not associated with a pipeline" %
                             (build_set,))
            if request.fulfilled:
                self.nodepool.returnNodeSet(request.nodeset)
            return
        pipeline.manager.onNodesProvisioned(event)

    def formatStatusJSON(self, tenant_name):
        # TODOv3(jeblair): use tenants
        data = {}

        data['zuul_version'] = self.zuul_version
        websocket_url = get_default(self.config, 'web', 'websocket_url', None)

        if self._pause:
            ret = '<p><b>Queue only mode:</b> preparing to '
            if self._exit:
                ret += 'exit'
            ret += ', queue length: %s' % self.trigger_event_queue.qsize()
            ret += '</p>'
            data['message'] = ret

        data['trigger_event_queue'] = {}
        data['trigger_event_queue']['length'] = \
            self.trigger_event_queue.qsize()
        data['result_event_queue'] = {}
        data['result_event_queue']['length'] = \
            self.result_event_queue.qsize()
        data['management_event_queue'] = {}
        data['management_event_queue']['length'] = \
            self.management_event_queue.qsize()

        if self.last_reconfigured:
            data['last_reconfigured'] = self.last_reconfigured * 1000

        pipelines = []
        data['pipelines'] = pipelines
        tenant = self.abide.tenants.get(tenant_name)
        for pipeline in tenant.layout.pipelines.values():
            pipelines.append(pipeline.formatStatusJSON(websocket_url))
        return json.dumps(data)

    def onChangeUpdated(self, change):
        """Remove stale dependency references on change update.

        When a change is updated with a new patchset, other changes in
        the system may still have a reference to the old patchset in
        their dependencies.  Search for those (across all sources) and
        mark that their dependencies are out of date.  This will cause
        them to be refreshed the next time the queue processor
        examines them.
        """

        self.log.debug("Change %s has been updated, clearing dependent "
                       "change caches", change)
        for source in self.connections.getSources():
            for other_change in source.getCachedChanges():
                if other_change.commit_needs_changes is None:
                    continue
                for dep in other_change.commit_needs_changes:
                    if change.isUpdateOf(dep):
                        other_change.refresh_deps = True
        change.refresh_deps = True
