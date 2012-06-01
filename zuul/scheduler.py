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

import os
import Queue
import threading
import logging
import re
import yaml

from model import Job, Change, Project, ChangeQueue, EventFilter


class Scheduler(threading.Thread):
    log = logging.getLogger("zuul.Scheduler")

    def __init__(self):
        threading.Thread.__init__(self)
        self.wake_event = threading.Event()
        self.reconfigure_complete_event = threading.Event()
        self.launcher = None
        self.trigger = None

        self.trigger_event_queue = Queue.Queue()
        self.result_event_queue = Queue.Queue()
        self._init()

    def _init(self):
        self.queue_managers = {}
        self.jobs = {}
        self.projects = {}
        self.metajobs = {}

    def _parseConfig(self, fp):
        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        if fp:
            fp = os.path.expanduser(fp)
            if not os.path.exists(fp):
                raise Exception("Unable to read layout config file at %s" % fp)
        fp = open(fp)
        data = yaml.load(fp)

        for config_queue in data['queue']:
            manager = globals()[config_queue['manager']](self,
                                                         config_queue['name'])
            self.queue_managers[config_queue['name']] = manager
            manager.success_action = config_queue.get('success')
            manager.failure_action = config_queue.get('failure')
            for trigger in toList(config_queue['trigger']):
                approvals = {}
                for approval_dict in toList(trigger.get('approval')):
                    for k, v in approval_dict.items():
                        approvals[k] = v
                f = EventFilter(types=toList(trigger['event']),
                                branches=toList(trigger.get('branch')),
                                refs=toList(trigger.get('ref')),
                                approvals=approvals)
                manager.event_filters.append(f)

        for config_job in data['jobs']:
            job = self.getJob(config_job['name'])
            # Be careful to only set attributes explicitly present on
            # this job, to avoid squashing attributes set by a meta-job.
            m = config_job.get('failure-message', None)
            if m:
                job.failure_message = m
            m = config_job.get('success-message', None)
            if m:
                job.success_message = m
            branches = toList(config_job.get('branch'))
            if branches:
                f = EventFilter(branches=branches)
                job.event_filters = [f]

        def add_jobs(job_tree, config_jobs):
            for job in config_jobs:
                if isinstance(job, list):
                    for x in job:
                        add_jobs(job_tree, x)
                if isinstance(job, dict):
                    for parent, children in job.items():
                        parent_tree = job_tree.addJob(self.getJob(parent))
                        add_jobs(parent_tree, children)
                if isinstance(job, str):
                    job_tree.addJob(self.getJob(job))

        for config_project in data['projects']:
            project = Project(config_project['name'])
            self.projects[config_project['name']] = project
            for qname in self.queue_managers.keys():
                if qname in config_project:
                    job_tree = project.addQueue(qname)
                    config_jobs = config_project[qname]
                    add_jobs(job_tree, config_jobs)

        # All jobs should be defined at this point, get rid of
        # metajobs so that getJob isn't doing anything weird.
        self.metajobs = {}

        # TODO(jeblair): check that we don't end up with jobs like
        # "foo - bar" because a ':' is missing in the yaml for a dependent job
        for manager in self.queue_managers.values():
            manager._postConfig()

    def getJob(self, name):
        if name in self.jobs:
            return self.jobs[name]
        job = Job(name)
        if name.startswith('^'):
            # This is a meta-job
            regex = re.compile(name)
            self.metajobs[regex] = job
        else:
            # Apply attributes from matching meta-jobs
            for regex, metajob in self.metajobs.items():
                if regex.match(name):
                    job.copy(metajob)
            self.jobs[name] = job
        return job

    def setLauncher(self, launcher):
        self.launcher = launcher

    def setTrigger(self, trigger):
        self.trigger = trigger

    def addEvent(self, event):
        self.log.debug("Adding trigger event: %s" % event)
        self.trigger_event_queue.put(event)
        self.wake_event.set()

    def onBuildCompleted(self, build):
        self.log.debug("Adding result event for build: %s" % build)
        self.result_event_queue.put(build)
        self.wake_event.set()

    def reconfigure(self, config):
        self.log.debug("Reconfigure")
        self.config = config
        self._reconfigure_flag = True
        self.wake_event.set()
        self.log.debug("Waiting for reconfiguration")
        self.reconfigure_complete_event.wait()
        self.reconfigure_complete_event.clear()
        self.log.debug("Reconfiguration complete")

    def _doReconfigure(self):
        self.log.debug("Performing reconfiguration")
        self._init()
        self._parseConfig(self.config.get('zuul', 'layout_config'))
        self._reconfigure_flag = False
        self.reconfigure_complete_event.set()

    def _areAllBuildsComplete(self):
        self.log.debug("Checking if all builds are complete")
        waiting = False
        for manager in self.queue_managers.values():
            for build in manager.building_jobs.values():
                self.log.debug("%s waiting on %s" % (manager, build))
                waiting = True
        if not waiting:
            self.log.debug("All builds are complete")
            return True
        self.log.debug("All builds are not complete")
        return False

    def run(self):
        while True:
            self.log.debug("Run handler sleeping")
            self.wake_event.wait()
            self.wake_event.clear()
            self.log.debug("Run handler awake")
            try:
                if not self._reconfigure_flag:
                    if not self.trigger_event_queue.empty():
                        self.process_event_queue()

                if not self.result_event_queue.empty():
                    self.process_result_queue()

                if self._reconfigure_flag and self._areAllBuildsComplete():
                    self._doReconfigure()

                if not (self.trigger_event_queue.empty() and
                        self.result_event_queue.empty()):
                    self.wake_event.set()
            except:
                self.log.exception("Exception in run handler:")

    def process_event_queue(self):
        self.log.debug("Fetching trigger event")
        event = self.trigger_event_queue.get()
        self.log.debug("Processing trigger event %s" % event)
        project = self.projects.get(event.project_name)
        if not project:
            self.log.warning("Project %s not found" % event.project_name)
            return

        for manager in self.queue_managers.values():
            if not manager.eventMatches(event):
                self.log.debug("Event %s ignored by %s" % (event, manager))
                continue
            change = Change(manager.name, project, event)
            self.log.info("Adding %s, %s to to %s" % (
                    project, change, manager))
            manager.addChange(change)

    def process_result_queue(self):
        self.log.debug("Fetching result event")
        build = self.result_event_queue.get()
        self.log.debug("Processing result event %s" % build)
        for manager in self.queue_managers.values():
            if manager.onBuildCompleted(build):
                return
        self.log.warning("Build %s not found by any queue manager" % (build))


class BaseQueueManager(object):
    log = logging.getLogger("zuul.BaseQueueManager")

    def __init__(self, sched, name):
        self.sched = sched
        self.name = name
        self.building_jobs = {}
        self.event_filters = []
        self.success_action = {}
        self.failure_action = {}

    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self.name)

    def _postConfig(self):
        self.log.info("Configured Queue Manager %s" % self.name)
        self.log.info("  Events:")
        for e in self.event_filters:
            self.log.info("    %s" % e)
        self.log.info("  Projects:")

        def log_jobs(tree, indent=0):
            istr = '    ' + ' ' * indent
            if tree.job:
                efilters = ''
                for e in tree.job.event_filters:
                    efilters += str(e)
                if efilters:
                    efilters = ' ' + efilters
                self.log.info("%s%s%s" % (istr, repr(tree.job), efilters))
            for x in tree.job_trees:
                log_jobs(x, indent + 2)

        for p in self.sched.projects.values():
            if p.hasQueue(self.name):
                self.log.info("    %s" % p)
                log_jobs(p.getJobTreeForQueue(self.name))
        if self.success_action:
            self.log.info("  On success:")
            self.log.info("    %s" % self.success_action)
        if self.failure_action:
            self.log.info("  On failure:")
            self.log.info("    %s" % self.failure_action)

    def eventMatches(self, event):
        for ef in self.event_filters:
            if ef.matches(event):
                return True
        return False

    def addChange(self, change):
        self.log.debug("Adding change %s" % change)
        self.launchJobs(change)

    def launchJobs(self, change):
        self.log.debug("Launching jobs for change %s" % change)
        for job in change.findJobsToRun():
            self.log.debug("Found job %s for change %s" % (job, change))
            try:
                build = self.sched.launcher.launch(job, change)
                self.building_jobs[build] = change
                self.log.debug("Adding build %s of job %s to change %s" % (
                        build, job, change))
                change.addBuild(build)
            except:
                self.log.exception("Exception while launching job %s \
for change %s:" % (job, change))

    def onBuildCompleted(self, build):
        self.log.debug("Build %s completed" % build)
        if build not in self.building_jobs:
            self.log.debug("Build %s not found" % (build))
            # Or triggered externally, or triggered before zuul started,
            # or restarted
            return False
        change = self.building_jobs[build]
        self.log.debug("Found change %s which triggered completed build %s" % (
                change, build))

        del self.building_jobs[build]

        change.setResult(build)
        self.log.info("Change %s status is now:\n %s" % (
                change, change.formatStatus()))

        if change.areAllJobsComplete():
            self.log.debug("All jobs for change %s are complete" % change)
            self.possiblyReportChange(change)
        else:
            # There may be jobs that depended on jobs that are now complete
            self.log.debug("All jobs for change %s are not yet complete" % (
                    change))
            self.launchJobs(change)
        return True

    def possiblyReportChange(self, change):
        self.log.debug("Possibly reporting change %s" % change)
        self.reportChange(change)

    def reportChange(self, change):
        self.log.debug("Reporting change %s" % change)
        ret = None
        if change.didAllJobsSucceed():
            action = self.success_action
        else:
            action = self.failure_action
        try:
            self.log.info("Reporting change %s, action: %s" % (
                    change, action))
            ret = self.sched.trigger.report(change, change.formatReport(),
                                            action)
            if ret:
                self.log.error("Reporting change %s received: %s" % (
                        change, ret))
        except:
            self.log.exception("Exception while reporting:")
        return ret


class IndependentQueueManager(BaseQueueManager):
    log = logging.getLogger("zuul.IndependentQueueManager")
    pass


class DependentQueueManager(BaseQueueManager):
    log = logging.getLogger("zuul.DependentQueueManager")

    def __init__(self, *args, **kwargs):
        super(DependentQueueManager, self).__init__(*args, **kwargs)
        self.change_queues = []

    def _postConfig(self):
        super(DependentQueueManager, self)._postConfig()
        self.buildChangeQueues()

    def buildChangeQueues(self):
        self.log.debug("Building shared change queues")
        change_queues = []

        for project in self.sched.projects.values():
            if project.hasQueue(self.name):
                change_queue = ChangeQueue(self.name)
                change_queue.addProject(project)
                change_queues.append(change_queue)
                self.log.debug("Created queue: %s" % change_queue)

        self.log.debug("Combining shared queues")
        new_change_queues = []
        for a in change_queues:
            merged_a = False
            for b in new_change_queues:
                if not a.getJobs().isdisjoint(b.getJobs()):
                    self.log.debug("Merging queue %s into %s" % (a, b))
                    b.mergeChangeQueue(a)
                    merged_a = True
                    break  # this breaks out of 'for b' and continues 'for a'
            if not merged_a:
                self.log.debug("Keeping queue %s" % (a))
                new_change_queues.append(a)

        self.change_queues = new_change_queues
        self.log.info("  Shared change queues:")
        for x in self.change_queues:
            self.log.info("    %s" % x)

    def getQueue(self, project):
        for queue in self.change_queues:
            if project in queue.projects:
                return queue
        self.log.error("Unable to find change queue for project %s" % project)

    def addChange(self, change):
        self.log.debug("Adding change %s" % change)
        change_queue = self.getQueue(change.project)
        self.log.debug("Adding change %s to queue %s" % (change, change_queue))
        change_queue.enqueueChange(change)
        super(DependentQueueManager, self).addChange(change)

    def _getDependentChanges(self, change):
        changes = []
        while change.change_ahead:
            changes.append(change.change_ahead)
            change = change.change_ahead
        self.log.info("Change %s depends on changes %s" % (change, changes))
        return changes

    def launchJobs(self, change):
        self.log.debug("Launching jobs for change %s" % change)
        dependent_changes = self._getDependentChanges(change)
        for job in change.findJobsToRun():
            self.log.debug("Found job %s for change %s" % (job, change))
            try:
                build = self.sched.launcher.launch(job, change,
                                                   dependent_changes)
                self.building_jobs[build] = change
                self.log.debug("Adding build %s of job %s to change %s" % (
                        build, job, change))
                change.addBuild(build)
            except:
                self.log.exception("Exception while launching job %s \
for change %s:" % (job, change))
        if change.change_behind:
            self.log.debug("Launching jobs for change %s, behind change %s" % (
                    change.change_behind, change))
            self.launchJobs(change.change_behind)

    def cancelJobs(self, change):
        self.log.debug("Cancel jobs for change %s" % change)
        to_remove = []
        change.resetAllBuilds()
        for build, build_change in self.building_jobs.items():
            if build_change == change:
                self.log.debug("Found build %s for change %s to cancel" % (
                        build, change))
                try:
                    self.sched.launcher.cancel(build)
                except:
                    self.log.exception("Exception while canceling build %s \
for change %s" % (build, change))
                to_remove.append(build)
        for build in to_remove:
            self.log.debug("Removing build %s from running builds" % build)
            del self.building_jobs[build]
        if change.change_behind:
            self.log.debug("Canceling jobs for change %s, \
behind change %s" % (change.change_behind, change))
            self.cancelJobs(change.change_behind)

    def possiblyReportChange(self, change):
        self.log.debug("Possibly reporting change %s" % change)
        if not change.change_ahead:
            self.log.debug("Change %s is at the front of the queue, \
reporting" % (change))
            ret = self.reportChange(change)
            self.log.debug("Removing reported change %s from queue" % change)
            change.delete()
            change.queue.dequeueChange(change)
            merged = (not ret)
            if merged:
                merged = self.sched.trigger.isMerged(change)
            succeeded = change.didAllJobsSucceed()
            self.log.info("Reported change %s status: all-succeeded: %s, \
merged: %s" % (change, succeeded, merged))

            if not (succeeded and merged):
                self.log.debug("Reported change %s failed tests or failed \
to merge" % (change))
                # The merge or test failed, re-run all jobs behind this one
                if change.change_behind:
                    self.log.info("Canceling/relaunching jobs for change %s \
behind failed change %s" % (
                            change.change_behind, change))
                    self.cancelJobs(change.change_behind)
                    self.launchJobs(change.change_behind)
        # If the change behind this is ready, notify
        if (change.change_behind and
            change.change_behind.areAllJobsComplete()):
            self.log.info("Change %s behind change %s is ready, \
possibly reporting" % (change.change_behind, change))
            self.possiblyReportChange(change.change_behind)
