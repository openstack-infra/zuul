# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import extras
import json
import logging
import os
import pickle
import Queue
import re
import threading
import time
import yaml

import layoutvalidator
import model
from model import Pipeline, Project, ChangeQueue, EventFilter
import merger

statsd = extras.try_import('statsd.statsd')


def deep_format(obj, paramdict):
    """Apply the paramdict via str.format() to all string objects found within
       the supplied obj. Lists and dicts are traversed recursively.

       Borrowed from Jenkins Job Builder project"""
    if isinstance(obj, str):
        ret = obj.format(**paramdict)
    elif isinstance(obj, list):
        ret = []
        for item in obj:
            ret.append(deep_format(item, paramdict))
    elif isinstance(obj, dict):
        ret = {}
        for item in obj:
            exp_item = item.format(**paramdict)

            ret[exp_item] = deep_format(obj[item], paramdict)
    else:
        ret = obj
    return ret


class MergeFailure(Exception):
    pass


class Scheduler(threading.Thread):
    log = logging.getLogger("zuul.Scheduler")

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.wake_event = threading.Event()
        self.layout_lock = threading.Lock()
        self.reconfigure_complete_event = threading.Event()
        self._pause = False
        self._reconfigure = False
        self._exit = False
        self._stopped = False
        self.launcher = None
        self.triggers = dict()
        self.config = None
        self._maintain_trigger_cache = False

        self.trigger_event_queue = Queue.Queue()
        self.result_event_queue = Queue.Queue()
        self.layout = model.Layout()

    def stop(self):
        self._stopped = True
        self.wake_event.set()

    def testConfig(self, config_path):
        return self._parseConfig(config_path)

    def _parseConfig(self, config_path):
        layout = model.Layout()
        project_templates = {}

        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        if config_path:
            config_path = os.path.expanduser(config_path)
            if not os.path.exists(config_path):
                raise Exception("Unable to read layout config file at %s" %
                                config_path)
        config_file = open(config_path)
        data = yaml.load(config_file)

        validator = layoutvalidator.LayoutValidator()
        validator.validate(data)

        config_env = {}
        for include in data.get('includes', []):
            if 'python-file' in include:
                fn = include['python-file']
                if not os.path.isabs(fn):
                    base = os.path.dirname(config_path)
                    fn = os.path.join(base, fn)
                fn = os.path.expanduser(fn)
                execfile(fn, config_env)

        for conf_pipeline in data.get('pipelines', []):
            pipeline = Pipeline(conf_pipeline['name'])
            pipeline.description = conf_pipeline.get('description')
            precedence = model.PRECEDENCE_MAP[conf_pipeline.get('precedence')]
            pipeline.precedence = precedence
            pipeline.failure_message = conf_pipeline.get('failure-message',
                                                         "Build failed.")
            pipeline.success_message = conf_pipeline.get('success-message',
                                                         "Build succeeded.")
            pipeline.dequeue_on_new_patchset = conf_pipeline.get(
                'dequeue-on-new-patchset', True)
            pipeline.dequeue_on_conflict = conf_pipeline.get(
                'dequeue-on-conflict', True)
            manager = globals()[conf_pipeline['manager']](self, pipeline)
            pipeline.setManager(manager)

            layout.pipelines[conf_pipeline['name']] = pipeline
            manager.success_action = conf_pipeline.get('success')
            manager.failure_action = conf_pipeline.get('failure')
            manager.start_action = conf_pipeline.get('start')
            # TODO: move this into triggers (may require pluggable
            # configuration)
            if 'gerrit' in conf_pipeline['trigger']:
                pipeline.trigger = self.triggers['gerrit']
                for trigger in toList(conf_pipeline['trigger']['gerrit']):
                    approvals = {}
                    for approval_dict in toList(trigger.get('approval')):
                        for k, v in approval_dict.items():
                            approvals[k] = v
                    f = EventFilter(types=toList(trigger['event']),
                                    branches=toList(trigger.get('branch')),
                                    refs=toList(trigger.get('ref')),
                                    approvals=approvals,
                                    comment_filters=
                                    toList(trigger.get('comment_filter')),
                                    email_filters=
                                    toList(trigger.get('email_filter')))
                    manager.event_filters.append(f)
            elif 'timer' in conf_pipeline['trigger']:
                pipeline.trigger = self.triggers['timer']
                for trigger in toList(conf_pipeline['trigger']['timer']):
                    f = EventFilter(types=['timer'],
                                    timespecs=toList(trigger['time']))
                    manager.event_filters.append(f)

        for project_template in data.get('project-templates', []):
            # Make sure the template only contains valid pipelines
            tpl = dict(
                (pipe_name, project_template.get(pipe_name))
                for pipe_name in layout.pipelines.keys()
                if pipe_name in project_template
            )
            project_templates[project_template.get('name')] = tpl

        for config_job in data.get('jobs', []):
            job = layout.getJob(config_job['name'])
            # Be careful to only set attributes explicitly present on
            # this job, to avoid squashing attributes set by a meta-job.
            m = config_job.get('failure-message', None)
            if m:
                job.failure_message = m
            m = config_job.get('success-message', None)
            if m:
                job.success_message = m
            m = config_job.get('failure-pattern', None)
            if m:
                job.failure_pattern = m
            m = config_job.get('success-pattern', None)
            if m:
                job.success_pattern = m
            m = config_job.get('hold-following-changes', False)
            if m:
                job.hold_following_changes = True
            m = config_job.get('voting', None)
            if m is not None:
                job.voting = m
            fname = config_job.get('parameter-function', None)
            if fname:
                func = config_env.get(fname, None)
                if not func:
                    raise Exception("Unable to find function %s" % fname)
                job.parameter_function = func
            branches = toList(config_job.get('branch'))
            if branches:
                job._branches = branches
                job.branches = [re.compile(x) for x in branches]
            files = toList(config_job.get('files'))
            if files:
                job._files = files
                job.files = [re.compile(x) for x in files]

        def add_jobs(job_tree, config_jobs):
            for job in config_jobs:
                if isinstance(job, list):
                    for x in job:
                        add_jobs(job_tree, x)
                if isinstance(job, dict):
                    for parent, children in job.items():
                        parent_tree = job_tree.addJob(layout.getJob(parent))
                        add_jobs(parent_tree, children)
                if isinstance(job, str):
                    job_tree.addJob(layout.getJob(job))

        for config_project in data.get('projects', []):
            project = Project(config_project['name'])

            for requested_template in config_project.get('template', []):
                # Fetch the template from 'project-templates'
                tpl = project_templates.get(
                    requested_template.get('name'))
                # Expand it with the project context
                expanded = deep_format(tpl, requested_template)
                # Finally merge the expansion with whatever has been already
                # defined for this project
                config_project.update(expanded)

            layout.projects[config_project['name']] = project
            mode = config_project.get('merge-mode', 'merge-resolve')
            project.merge_mode = model.MERGER_MAP[mode]
            for pipeline in layout.pipelines.values():
                if pipeline.name in config_project:
                    job_tree = pipeline.addProject(project)
                    config_jobs = config_project[pipeline.name]
                    add_jobs(job_tree, config_jobs)

        # All jobs should be defined at this point, get rid of
        # metajobs so that getJob isn't doing anything weird.
        layout.metajobs = []

        for pipeline in layout.pipelines.values():
            pipeline.manager._postConfig(layout)

        return layout

    def _setupMerger(self):
        if self.config.has_option('zuul', 'git_dir'):
            merge_root = self.config.get('zuul', 'git_dir')
        else:
            merge_root = '/var/lib/zuul/git'

        if self.config.has_option('zuul', 'git_user_email'):
            merge_email = self.config.get('zuul', 'git_user_email')
        else:
            merge_email = None

        if self.config.has_option('zuul', 'git_user_name'):
            merge_name = self.config.get('zuul', 'git_user_name')
        else:
            merge_name = None

        if self.config.has_option('zuul', 'push_change_refs'):
            push_refs = self.config.getboolean('zuul', 'push_change_refs')
        else:
            push_refs = False

        if self.config.has_option('gerrit', 'sshkey'):
            sshkey = self.config.get('gerrit', 'sshkey')
        else:
            sshkey = None

        # TODO: The merger should have an upstream repo independent of
        # triggers, and then each trigger should provide a fetch
        # location.
        self.merger = merger.Merger(self.triggers['gerrit'],
                                    merge_root, push_refs,
                                    sshkey, merge_email, merge_name)
        for project in self.layout.projects.values():
            url = self.triggers['gerrit'].getGitUrl(project)
            self.merger.addProject(project, url)

    def setLauncher(self, launcher):
        self.launcher = launcher

    def registerTrigger(self, trigger, name=None):
        if name is None:
            name = trigger.name
        self.triggers[name] = trigger

    def getProject(self, name):
        self.layout_lock.acquire()
        p = None
        try:
            p = self.layout.projects.get(name)
        finally:
            self.layout_lock.release()
        return p

    def addEvent(self, event):
        self.log.debug("Adding trigger event: %s" % event)
        try:
            if statsd:
                statsd.incr('gerrit.event.%s' % event.type)
        except:
            self.log.exception("Exception reporting event stats")
        self.trigger_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Done adding trigger event: %s" % event)

    def onBuildStarted(self, build):
        self.log.debug("Adding start event for build: %s" % build)
        build.start_time = time.time()
        self.result_event_queue.put(('started', build))
        self.wake_event.set()
        self.log.debug("Done adding start event for build: %s" % build)

    def onBuildCompleted(self, build):
        self.log.debug("Adding complete event for build: %s" % build)
        build.end_time = time.time()
        try:
            if statsd and build.pipeline:
                jobname = build.job.name.replace('.', '_')
                key = 'zuul.pipeline.%s.job.%s.%s' % (build.pipeline.name,
                                                      jobname, build.result)
                if build.result in ['SUCCESS', 'FAILURE'] and build.start_time:
                    dt = int((build.end_time - build.start_time) * 1000)
                    statsd.timing(key, dt)
                statsd.incr(key)
                key = 'zuul.pipeline.%s.all_jobs' % build.pipeline.name
                statsd.incr(key)
        except:
            self.log.exception("Exception reporting runtime stats")
        self.result_event_queue.put(('completed', build))
        self.wake_event.set()
        self.log.debug("Done adding complete event for build: %s" % build)

    def reconfigure(self, config):
        self.log.debug("Prepare to reconfigure")
        self.config = config
        self._reconfigure = True
        self.wake_event.set()
        self.log.debug("Waiting for reconfiguration")
        self.reconfigure_complete_event.wait()
        self.reconfigure_complete_event.clear()
        self.log.debug("Reconfiguration complete")

    def exit(self):
        self.log.debug("Prepare to exit")
        self._pause = True
        self._exit = True
        self.wake_event.set()
        self.log.debug("Waiting for exit")

    def _get_queue_pickle_file(self):
        if self.config.has_option('zuul', 'state_dir'):
            state_dir = os.path.expanduser(self.config.get('zuul',
                                                           'state_dir'))
        else:
            state_dir = '/var/lib/zuul'
        return os.path.join(state_dir, 'queue.pickle')

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
        except:
            self.log.exception("Unable to load queue")
        try:
            self._delete_queue()
        except:
            self.log.exception("Unable to delete saved queue")
        self.log.debug("Resuming queue processing")
        self.wake_event.set()

    def _doPauseEvent(self):
        if self._exit:
            self.log.debug("Exiting")
            self._save_queue()
            os._exit(0)

    def _doReconfigureEvent(self):
        # This is called in the scheduler loop after another thread sets
        # the reconfigure flag
        self.layout_lock.acquire()
        try:
            self.log.debug("Performing reconfiguration")
            layout = self._parseConfig(
                self.config.get('zuul', 'layout_config'))
            for name, new_pipeline in layout.pipelines.items():
                old_pipeline = self.layout.pipelines.get(name)
                if not old_pipeline:
                    if self.layout.pipelines:
                        # Don't emit this warning on startup
                        self.log.warning("No old pipeline matching %s found "
                                         "when reconfiguring" % name)
                    continue
                self.log.debug("Re-enqueueing changes for pipeline %s" %
                               name)
                items_to_remove = []
                for shared_queue in old_pipeline.queues:
                    for item in (shared_queue.queue +
                                 shared_queue.severed_heads):
                        item.item_ahead = None
                        item.item_behind = None
                        item.pipeline = None
                        project = layout.projects.get(item.change.project.name)
                        if not project:
                            self.log.warning("Unable to find project for "
                                             "change %s while reenqueueing" %
                                             item.change)
                            item.change.project = None
                            items_to_remove.append(item)
                            continue
                        item.change.project = project
                        severed = item in shared_queue.severed_heads
                        if not new_pipeline.manager.reEnqueueItem(
                            item, severed=severed):
                            items_to_remove.append(item)
                builds_to_remove = []
                for build, item in old_pipeline.manager.building_jobs.items():
                    if item in items_to_remove:
                        builds_to_remove.append(build)
                        self.log.warning("Deleting running build %s for "
                                         "change %s while reenqueueing" % (
                                         build, item.change))
                for build in builds_to_remove:
                    del old_pipeline.manager.building_jobs[build]
                new_pipeline.manager.building_jobs = \
                    old_pipeline.manager.building_jobs
            self.layout = layout
            self._setupMerger()
            for trigger in self.triggers.values():
                trigger.postConfig()
            self._reconfigure = False
            self.reconfigure_complete_event.set()
        finally:
            self.layout_lock.release()

    def _areAllBuildsComplete(self):
        self.log.debug("Checking if all builds are complete")
        waiting = False
        for pipeline in self.layout.pipelines.values():
            for build in pipeline.manager.building_jobs.keys():
                self.log.debug("%s waiting on %s" % (pipeline.manager, build))
                waiting = True
        if not waiting:
            self.log.debug("All builds are complete")
            return True
        self.log.debug("All builds are not complete")
        return False

    def run(self):
        if statsd:
            self.log.debug("Statsd enabled")
        else:
            self.log.debug("Statsd disabled because python statsd "
                           "package not found")
        while True:
            self.log.debug("Run handler sleeping")
            self.wake_event.wait()
            self.wake_event.clear()
            if self._stopped:
                return
            self.log.debug("Run handler awake")
            try:
                if self._reconfigure:
                    self._doReconfigureEvent()

                # Give result events priority -- they let us stop builds,
                # whereas trigger evensts cause us to launch builds.
                if not self.result_event_queue.empty():
                    self.process_result_queue()
                elif not self._pause:
                    if not self.trigger_event_queue.empty():
                        self.process_event_queue()

                if self._pause and self._areAllBuildsComplete():
                    self._doPauseEvent()

                if not self._pause:
                    if not (self.trigger_event_queue.empty() and
                            self.result_event_queue.empty()):
                        self.wake_event.set()
                else:
                    if not self.result_event_queue.empty():
                        self.wake_event.set()

                if self._maintain_trigger_cache:
                    self.maintainTriggerCache()
                    self._maintain_trigger_cache = False

            except:
                self.log.exception("Exception in run handler:")

    def maintainTriggerCache(self):
        relevant = set()
        for pipeline in self.layout.pipelines.values():
            self.log.debug("Start maintain trigger cache for: %s" % pipeline)
            for item in pipeline.getAllItems():
                relevant.add(item.change)
                relevant.update(item.change.getRelatedChanges())
            self.log.debug("End maintain trigger cache for: %s" % pipeline)
        self.log.debug("Trigger cache size: %s" % len(relevant))
        for trigger in self.triggers.values():
            trigger.maintainCache(relevant)

    def process_event_queue(self):
        self.log.debug("Fetching trigger event")
        event = self.trigger_event_queue.get()
        self.log.debug("Processing trigger event %s" % event)
        project = self.layout.projects.get(event.project_name)
        if not project:
            self.log.warning("Project %s not found" % event.project_name)
            self.trigger_event_queue.task_done()
            return

        # Preprocessing for ref-update events
        if event.ref:
            # Make sure the local git repo is up-to-date with the remote one.
            # We better have the new ref before enqueuing the changes.
            # This is done before enqueuing the changes to avoid calling an
            # update per pipeline accepting the change.
            self.log.info("Fetching updated ref %s for %s" %
                          (event.ref, project))
            self.merger.updateRepo(project, event.ref)

        for pipeline in self.layout.pipelines.values():
            change = event.getChange(project,
                                     self.triggers.get(event.trigger_name))
            if event.type == 'patchset-created':
                pipeline.manager.removeOldVersionsOfChange(change)
            if pipeline.manager.eventMatches(event):
                self.log.info("Adding %s, %s to %s" %
                              (project, change, pipeline))
                pipeline.manager.addChange(change)
            while pipeline.manager.processQueue():
                pass

        self.trigger_event_queue.task_done()

    def process_result_queue(self):
        self.log.debug("Fetching result event")
        event_type, build = self.result_event_queue.get()
        self.log.debug("Processing result event %s" % build)
        for pipeline in self.layout.pipelines.values():
            if event_type == 'started':
                if pipeline.manager.onBuildStarted(build):
                    self.result_event_queue.task_done()
                    return
            elif event_type == 'completed':
                if pipeline.manager.onBuildCompleted(build):
                    self.result_event_queue.task_done()
                    return
        self.log.warning("Build %s not found by any queue manager" % (build))
        self.result_event_queue.task_done()

    def formatStatusHTML(self):
        ret = '<html><pre>'
        if self._pause:
            ret += '<p><b>Queue only mode:</b> preparing to '
            if self._exit:
                ret += 'exit'
            ret += ', queue length: %s' % self.trigger_event_queue.qsize()
            ret += '</p>'

        keys = self.layout.pipelines.keys()
        for key in keys:
            pipeline = self.layout.pipelines[key]
            s = 'Pipeline: %s' % pipeline.name
            ret += s + '\n'
            ret += '-' * len(s) + '\n'
            ret += pipeline.formatStatusHTML()
            ret += '\n'
        ret += '</pre></html>'
        return ret

    def formatStatusJSON(self):
        data = {}
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

        pipelines = []
        data['pipelines'] = pipelines
        keys = self.layout.pipelines.keys()
        for key in keys:
            pipeline = self.layout.pipelines[key]
            pipelines.append(pipeline.formatStatusJSON())
        return json.dumps(data)


class BasePipelineManager(object):
    log = logging.getLogger("zuul.BasePipelineManager")

    def __init__(self, sched, pipeline):
        self.sched = sched
        self.pipeline = pipeline
        self.building_jobs = {}
        self.event_filters = []
        self.success_action = {}
        self.failure_action = {}
        self.start_action = {}
        if self.sched.config and self.sched.config.has_option(
            'zuul', 'report_times'):
            self.report_times = self.sched.config.getboolean(
                'zuul', 'report_times')
        else:
            self.report_times = True

    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self.pipeline.name)

    def _postConfig(self, layout):
        self.log.info("Configured Pipeline Manager %s" % self.pipeline.name)
        self.log.info("  Events:")
        for e in self.event_filters:
            self.log.info("    %s" % e)
        self.log.info("  Projects:")

        def log_jobs(tree, indent=0):
            istr = '    ' + ' ' * indent
            if tree.job:
                efilters = ''
                for b in tree.job._branches:
                    efilters += str(b)
                for f in tree.job._files:
                    efilters += str(f)
                if efilters:
                    efilters = ' ' + efilters
                hold = ''
                if tree.job.hold_following_changes:
                    hold = ' [hold]'
                voting = ''
                if not tree.job.voting:
                    voting = ' [nonvoting]'
                self.log.info("%s%s%s%s%s" % (istr, repr(tree.job),
                                              efilters, hold, voting))
            for x in tree.job_trees:
                log_jobs(x, indent + 2)

        for p in layout.projects.values():
            tree = self.pipeline.getJobTree(p)
            if tree:
                self.log.info("    %s" % p)
                log_jobs(tree)
        if self.start_action:
            self.log.info("  On start:")
            self.log.info("    %s" % self.start_action)
        if self.success_action:
            self.log.info("  On success:")
            self.log.info("    %s" % self.success_action)
        if self.failure_action:
            self.log.info("  On failure:")
            self.log.info("    %s" % self.failure_action)

    def getSubmitAllowNeeds(self):
        # Get a list of code review labels that are allowed to be
        # "needed" in the submit records for a change, with respect
        # to this queue.  In other words, the list of review labels
        # this queue itself is likely to set before submitting.
        if self.success_action:
            return self.success_action.keys()
        else:
            return {}

    def eventMatches(self, event):
        for ef in self.event_filters:
            if ef.matches(event):
                return True
        return False

    def isChangeAlreadyInQueue(self, change):
        for c in self.pipeline.getChangesInQueue():
            if change.equals(c):
                return True
        return False

    def reportStart(self, change):
        try:
            self.log.info("Reporting start, action %s change %s" %
                          (self.start_action, change))
            msg = "Starting %s jobs." % self.pipeline.name
            if self.sched.config.has_option('zuul', 'status_url'):
                msg += "\n" + self.sched.config.get('zuul', 'status_url')
            ret = self.pipeline.trigger.report(change, msg, self.start_action)
            if ret:
                self.log.error("Reporting change start %s received: %s" %
                               (change, ret))
        except:
            self.log.exception("Exception while reporting start:")

    def isChangeReadyToBeEnqueued(self, change):
        return True

    def enqueueChangesAhead(self, change):
        return True

    def enqueueChangesBehind(self, change):
        return True

    def checkForChangesNeededBy(self, change):
        return True

    def getDependentItems(self, item):
        orig_item = item
        items = []
        while item.item_ahead:
            items.append(item.item_ahead)
            item = item.item_ahead
        self.log.info("Change %s depends on changes %s" %
                      (orig_item.change,
                       [x.change for x in items]))
        return items

    def findOldVersionOfChangeAlreadyInQueue(self, change):
        for c in self.pipeline.getChangesInQueue():
            if change.isUpdateOf(c):
                return c
        return None

    def removeOldVersionsOfChange(self, change):
        if not self.pipeline.dequeue_on_new_patchset:
            return
        old_change = self.findOldVersionOfChangeAlreadyInQueue(change)
        if old_change:
            self.log.debug("Change %s is a new version of %s, removing %s" %
                           (change, old_change, old_change))
            self.removeChange(old_change)

    def reEnqueueItem(self, item, severed=False):
        change_queue = self.pipeline.getQueue(item.change.project)
        if change_queue:
            self.log.debug("Re-enqueing change %s in queue %s" %
                           (item.change, change_queue))
            if severed:
                change_queue.addSeveredHead(item)
            else:
                change_queue.enqueueItem(item)
            self.reportStats(item)
            return True
        else:
            self.log.error("Unable to find change queue for project %s" %
                           item.change.project)
            return False

    def addChange(self, change):
        self.log.debug("Considering adding change %s" % change)
        if self.isChangeAlreadyInQueue(change):
            self.log.debug("Change %s is already in queue, ignoring" % change)
            return True

        if not self.isChangeReadyToBeEnqueued(change):
            self.log.debug("Change %s is not ready to be enqueued, ignoring" %
                           change)
            return False

        if not self.enqueueChangesAhead(change):
            self.log.debug("Failed to enqueue changes ahead of %s" % change)
            return False

        if self.isChangeAlreadyInQueue(change):
            self.log.debug("Change %s is already in queue, ignoring" % change)
            return True

        change_queue = self.pipeline.getQueue(change.project)
        if change_queue:
            self.log.debug("Adding change %s to queue %s" %
                           (change, change_queue))
            if self.start_action:
                self.reportStart(change)
            item = change_queue.enqueueChange(change)
            self.reportStats(item)
            self.enqueueChangesBehind(change)
        else:
            self.log.error("Unable to find change queue for project %s" %
                           change.project)
            return False

    def dequeueItem(self, item, keep_severed_heads=True):
        self.log.debug("Removing change %s from queue" % item.change)
        item_ahead = item.item_ahead
        change_queue = self.pipeline.getQueue(item.change.project)
        change_queue.dequeueItem(item)
        if (keep_severed_heads and not item_ahead and
            (item.change.is_reportable and not item.reported)):
            self.log.debug("Adding %s as a severed head" % item.change)
            change_queue.addSeveredHead(item)
        self.sched._maintain_trigger_cache = True

    def removeChange(self, change):
        # Remove a change from the queue, probably because it has been
        # superceded by another change.
        for item in self.pipeline.getAllItems():
            if item.change == change:
                self.log.debug("Canceling builds behind change: %s "
                               "because it is being removed." % item.change)
                self.cancelJobs(item)
                self.dequeueItem(item, keep_severed_heads=False)
                self.reportStats(item)

    def prepareRef(self, item):
        # Returns False on success.
        # Returns True if we were unable to prepare the ref.
        ref = item.current_build_set.ref
        if hasattr(item.change, 'refspec') and not ref:
            self.log.debug("Preparing ref for: %s" % item.change)
            item.current_build_set.setConfiguration()
            ref = item.current_build_set.ref
            dependent_items = self.getDependentItems(item)
            dependent_items.reverse()
            dependent_str = ', '.join(
                ['%s' % i.change.number for i in dependent_items
                 if i.change.project == item.change.project])
            if dependent_str:
                msg = \
                    "This change was unable to be automatically merged "\
                    "with the current state of the repository and the "\
                    "following changes which were enqueued ahead of it: "\
                    "%s. Please rebase your change and upload a new "\
                    "patchset." % dependent_str
            else:
                msg = "This change was unable to be automatically merged "\
                    "with the current state of the repository. Please "\
                    "rebase your change and upload a new patchset."
            all_items = dependent_items + [item]
            if (dependent_items and
                not dependent_items[-1].current_build_set.commit):
                self.pipeline.setUnableToMerge(item, msg)
                return True
            commit = self.sched.merger.mergeChanges(all_items, ref)
            item.current_build_set.commit = commit
            if not commit:
                self.log.info("Unable to merge change %s" % item.change)
                self.pipeline.setUnableToMerge(item, msg)
                return True
        return False

    def _launchJobs(self, item, jobs):
        self.log.debug("Launching jobs for change %s" % item.change)
        dependent_items = self.getDependentItems(item)
        for job in jobs:
            self.log.debug("Found job %s for change %s" % (job, item.change))
            try:
                build = self.sched.launcher.launch(job, item,
                                                   self.pipeline,
                                                   dependent_items)
                self.building_jobs[build] = item
                self.log.debug("Adding build %s of job %s to item %s" %
                               (build, job, item))
                item.addBuild(build)
            except:
                self.log.exception("Exception while launching job %s "
                                   "for change %s:" % (job, item.change))

    def launchJobs(self, item):
        jobs = self.pipeline.findJobsToRun(item)
        if jobs:
            self._launchJobs(item, jobs)

    def cancelJobs(self, item, prime=True):
        self.log.debug("Cancel jobs for change %s" % item.change)
        canceled = False
        to_remove = []
        if prime and item.current_build_set.builds:
            item.resetAllBuilds()
        for build, build_item in self.building_jobs.items():
            if build_item == item:
                self.log.debug("Found build %s for change %s to cancel" %
                               (build, item.change))
                try:
                    self.sched.launcher.cancel(build)
                except:
                    self.log.exception("Exception while canceling build %s "
                                       "for change %s" % (build, item.change))
                to_remove.append(build)
                canceled = True
        for build in to_remove:
            self.log.debug("Removing build %s from running builds" % build)
            build.result = 'CANCELED'
            del self.building_jobs[build]
        if item.item_behind:
            self.log.debug("Canceling jobs for change %s, behind change %s" %
                           (item.item_behind.change, item.change))
            if self.cancelJobs(item.item_behind, prime=prime):
                canceled = True
        return canceled

    def _processOneItem(self, item):
        changed = False
        item_ahead = item.item_ahead
        item_behind = item.item_behind
        if self.prepareRef(item):
            changed = True
            if self.pipeline.dequeue_on_conflict:
                self.log.info("Dequeuing change %s because "
                              "of a git merge error" % item.change)
                self.dequeueItem(item, keep_severed_heads=False)
                try:
                    self.reportItem(item)
                except MergeFailure:
                    pass
                return changed
        if self.checkForChangesNeededBy(item.change) is not True:
            # It's not okay to enqueue this change, we should remove it.
            self.log.info("Dequeuing change %s because "
                          "it can no longer merge" % item.change)
            self.cancelJobs(item)
            self.dequeueItem(item, keep_severed_heads=False)
            self.pipeline.setDequeuedNeedingChange(item)
            try:
                self.reportItem(item)
            except MergeFailure:
                pass
            changed = True
            return changed
        if not item_ahead:
            merge_failed = False
            if self.pipeline.areAllJobsComplete(item):
                try:
                    self.reportItem(item)
                except MergeFailure:
                    merge_failed = True
                self.dequeueItem(item)
                changed = True
            if merge_failed or self.pipeline.didAnyJobFail(item):
                if item_behind:
                    self.cancelJobs(item_behind)
                    changed = True
                    self.dequeueItem(item)
        else:
            if self.pipeline.didAnyJobFail(item):
                if item_behind:
                    if self.cancelJobs(item_behind, prime=False):
                        changed = True
                # don't restart yet; this change will eventually become
                # the head
        if self.launchJobs(item):
            changed = True
        return changed

    def processQueue(self):
        # Do whatever needs to be done for each change in the queue
        self.log.debug("Starting queue processor: %s" % self.pipeline.name)
        changed = False
        for item in self.pipeline.getAllItems():
            if self._processOneItem(item):
                changed = True
            self.reportStats(item)
        self.log.debug("Finished queue processor: %s (changed: %s)" %
                       (self.pipeline.name, changed))
        return changed

    def updateBuildDescriptions(self, build_set):
        for build in build_set.getBuilds():
            desc = self.formatDescription(build)
            self.sched.launcher.setBuildDescription(build, desc)

        if build_set.previous_build_set:
            for build in build_set.previous_build_set.getBuilds():
                desc = self.formatDescription(build)
                self.sched.launcher.setBuildDescription(build, desc)

    def onBuildStarted(self, build):
        if build not in self.building_jobs:
            # Or triggered externally, or triggered before zuul started,
            # or restarted
            return False

        self.log.debug("Build %s started" % build)
        self.updateBuildDescriptions(build.build_set)
        while self.processQueue():
            pass
        return True

    def onBuildCompleted(self, build):
        if build not in self.building_jobs:
            # Or triggered externally, or triggered before zuul started,
            # or restarted
            return False

        self.log.debug("Build %s completed" % build)
        change = self.building_jobs[build]
        self.log.debug("Found change %s which triggered completed build %s" %
                       (change, build))

        del self.building_jobs[build]

        self.pipeline.setResult(change, build)
        self.log.info("Change %s status is now:\n %s" %
                      (change, self.pipeline.formatStatus(change)))
        self.updateBuildDescriptions(build.build_set)
        while self.processQueue():
            pass
        return True

    def reportItem(self, item):
        if item.change.is_reportable and item.reported:
            raise Exception("Already reported change %s" % item.change)
        ret = self._reportItem(item)
        if self.changes_merge:
            succeeded = self.pipeline.didAllJobsSucceed(item)
            merged = (not ret)
            if merged:
                merged = self.pipeline.trigger.isMerged(item.change,
                                                        item.change.branch)
            self.log.info("Reported change %s status: all-succeeded: %s, "
                          "merged: %s" % (item.change, succeeded, merged))
            if not (succeeded and merged):
                self.log.debug("Reported change %s failed tests or failed "
                               "to merge" % (item.change))
                raise MergeFailure("Change %s failed to merge" % item.change)

    def _reportItem(self, item):
        if not item.change.is_reportable:
            return False
        if item.change.is_reportable and item.reported:
            return 0
        self.log.debug("Reporting change %s" % item.change)
        ret = True  # Means error as returned by trigger.report
        if self.pipeline.didAllJobsSucceed(item):
            self.log.debug("success %s %s" % (self.success_action,
                                              self.failure_action))
            action = self.success_action
            item.setReportedResult('SUCCESS')
        else:
            action = self.failure_action
            item.setReportedResult('FAILURE')
        report = self.formatReport(item)
        item.reported = True
        try:
            self.log.info("Reporting change %s, action: %s" %
                          (item.change, action))
            ret = self.pipeline.trigger.report(item.change, report, action)
            if ret:
                self.log.error("Reporting change %s received: %s" %
                               (item.change, ret))
        except:
            self.log.exception("Exception while reporting:")
            item.setReportedResult('ERROR')
        self.updateBuildDescriptions(item.current_build_set)
        return ret

    def formatReport(self, item):
        ret = ''
        if self.pipeline.didAllJobsSucceed(item):
            ret += self.pipeline.success_message + '\n\n'
        else:
            ret += self.pipeline.failure_message + '\n\n'

        if item.dequeued_needing_change:
            ret += "This change depends on a change that failed to merge."
        elif item.current_build_set.unable_to_merge_message:
            ret += item.current_build_set.unable_to_merge_message
        else:
            if self.sched.config.has_option('zuul', 'url_pattern'):
                url_pattern = self.sched.config.get('zuul', 'url_pattern')
            else:
                url_pattern = None
            for job in self.pipeline.getJobs(item.change):
                build = item.current_build_set.getBuild(job.name)
                result = build.result
                pattern = url_pattern
                if result == 'SUCCESS':
                    if job.success_message:
                        result = job.success_message
                    if job.success_pattern:
                        pattern = job.success_pattern
                elif result == 'FAILURE':
                    if job.failure_message:
                        result = job.failure_message
                    if job.failure_pattern:
                        pattern = job.failure_pattern
                if pattern:
                    url = pattern.format(change=item.change,
                                         pipeline=self.pipeline,
                                         job=job,
                                         build=build)
                else:
                    url = build.url or job.name
                if not job.voting:
                    voting = ' (non-voting)'
                else:
                    voting = ''
                if self.report_times and build.end_time and build.start_time:
                    dt = int(build.end_time - build.start_time)
                    m, s = divmod(dt, 60)
                    h, m = divmod(m, 60)
                    if h:
                        elapsed = ' in %dh %02dm %02ds' % (h, m, s)
                    elif m:
                        elapsed = ' in %dm %02ds' % (m, s)
                    else:
                        elapsed = ' in %ds' % (s)
                else:
                    elapsed = ''
                name = ''
                if self.sched.config.has_option('zuul', 'job_name_in_report'):
                    if self.sched.config.getboolean('zuul',
                                                    'job_name_in_report'):
                        name = job.name + ' '
                ret += '- %s%s : %s%s%s\n' % (name, url, result, elapsed,
                                              voting)
        return ret

    def formatDescription(self, build):
        concurrent_changes = ''
        concurrent_builds = ''
        other_builds = ''

        for change in build.build_set.other_changes:
            concurrent_changes += '<li><a href="{change.url}">\
              {change.number},{change.patchset}</a></li>'.format(
                change=change)

        change = build.build_set.item.change

        for build in build.build_set.getBuilds():
            if build.url:
                concurrent_builds += """\
<li>
  <a href="{build.url}">
  {build.job.name} #{build.number}</a>: {build.result}
</li>
""".format(build=build)
            else:
                concurrent_builds += """\
<li>
  {build.job.name}: {build.result}
</li>""".format(build=build)

        if build.build_set.previous_build_set:
            other_build = build.build_set.previous_build_set.getBuild(
                build.job.name)
            if other_build:
                other_builds += """\
<li>
  Preceded by: <a href="{build.url}">
  {build.job.name} #{build.number}</a>
</li>
""".format(build=other_build)

        if build.build_set.next_build_set:
            other_build = build.build_set.next_build_set.getBuild(
                build.job.name)
            if other_build:
                other_builds += """\
<li>
  Succeeded by: <a href="{build.url}">
  {build.job.name} #{build.number}</a>
</li>
""".format(build=other_build)

        result = build.build_set.result

        if hasattr(change, 'number'):
            ret = """\
<p>
  Triggered by change:
    <a href="{change.url}">{change.number},{change.patchset}</a><br/>
  Branch: <b>{change.branch}</b><br/>
  Pipeline: <b>{self.pipeline.name}</b>
</p>"""
        elif hasattr(change, 'ref'):
            ret = """\
<p>
  Triggered by reference:
    {change.ref}</a><br/>
  Old revision: <b>{change.oldrev}</b><br/>
  New revision: <b>{change.newrev}</b><br/>
  Pipeline: <b>{self.pipeline.name}</b>
</p>"""
        else:
            ret = ""

        if concurrent_changes:
            ret += """\
<p>
  Other changes tested concurrently with this change:
  <ul>{concurrent_changes}</ul>
</p>
"""
        if concurrent_builds:
            ret += """\
<p>
  All builds for this change set:
  <ul>{concurrent_builds}</ul>
</p>
"""

        if other_builds:
            ret += """\
<p>
  Other build sets for this change:
  <ul>{other_builds}</ul>
</p>
"""
        if result:
            ret += """\
<p>
  Reported result: <b>{result}</b>
</p>
"""

        ret = ret.format(**locals())
        return ret

    def reportStats(self, item):
        if not statsd:
            return
        try:
            # Update the gauge on enqueue and dequeue, but timers only
            # when dequeing.
            if item.dequeue_time:
                dt = int((item.dequeue_time - item.enqueue_time) * 1000)
            else:
                dt = None
            items = len(self.pipeline.getAllItems())

            # stats.timers.zuul.pipeline.NAME.resident_time
            # stats_counts.zuul.pipeline.NAME.total_changes
            # stats.gauges.zuul.pipeline.NAME.current_changes
            key = 'zuul.pipeline.%s' % self.pipeline.name
            statsd.gauge(key + '.current_changes', items)
            if dt:
                statsd.timing(key + '.resident_time', dt)
                statsd.incr(key + '.total_changes')

            # stats.timers.zuul.pipeline.NAME.ORG.PROJECT.resident_time
            # stats_counts.zuul.pipeline.NAME.ORG.PROJECT.total_changes
            project_name = item.change.project.name.replace('/', '.')
            key += '.%s' % project_name
            if dt:
                statsd.timing(key + '.resident_time', dt)
                statsd.incr(key + '.total_changes')
        except:
            self.log.exception("Exception reporting pipeline stats")


class IndependentPipelineManager(BasePipelineManager):
    log = logging.getLogger("zuul.IndependentPipelineManager")
    changes_merge = False

    def _postConfig(self, layout):
        super(IndependentPipelineManager, self)._postConfig(layout)

        change_queue = ChangeQueue(self.pipeline, dependent=False)
        for project in self.pipeline.getProjects():
            change_queue.addProject(project)

        self.pipeline.addQueue(change_queue)


class DependentPipelineManager(BasePipelineManager):
    log = logging.getLogger("zuul.DependentPipelineManager")
    changes_merge = True

    def __init__(self, *args, **kwargs):
        super(DependentPipelineManager, self).__init__(*args, **kwargs)

    def _postConfig(self, layout):
        super(DependentPipelineManager, self)._postConfig(layout)
        self.buildChangeQueues()

    def buildChangeQueues(self):
        self.log.debug("Building shared change queues")
        change_queues = []

        for project in self.pipeline.getProjects():
            change_queue = ChangeQueue(self.pipeline)
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

        self.log.info("  Shared change queues:")
        for queue in new_change_queues:
            self.pipeline.addQueue(queue)
            self.log.info("    %s" % queue)

    def isChangeReadyToBeEnqueued(self, change):
        if not self.pipeline.trigger.canMerge(change,
                                              self.getSubmitAllowNeeds()):
            self.log.debug("Change %s can not merge, ignoring" % change)
            return False
        return True

    def enqueueChangesBehind(self, change):
        to_enqueue = []
        self.log.debug("Checking for changes needing %s:" % change)
        if not hasattr(change, 'needed_by_changes'):
            self.log.debug("  Changeish does not support dependencies")
            return
        for needs in change.needed_by_changes:
            if self.pipeline.trigger.canMerge(needs,
                                              self.getSubmitAllowNeeds()):
                self.log.debug("  Change %s needs %s and is ready to merge" %
                               (needs, change))
                to_enqueue.append(needs)
        if not to_enqueue:
            self.log.debug("  No changes need %s" % change)

        for other_change in to_enqueue:
            self.addChange(other_change)

    def enqueueChangesAhead(self, change):
        ret = self.checkForChangesNeededBy(change)
        if ret in [True, False]:
            return ret
        self.log.debug("  Change %s must be merged ahead of %s" %
                       (ret, change))
        return self.addChange(ret)

    def checkForChangesNeededBy(self, change):
        self.log.debug("Checking for changes needed by %s:" % change)
        # Return true if okay to proceed enqueing this change,
        # false if the change should not be enqueued.
        if not hasattr(change, 'needs_change'):
            self.log.debug("  Changeish does not support dependencies")
            return True
        if not change.needs_change:
            self.log.debug("  No changes needed")
            return True
        if change.needs_change.is_merged:
            self.log.debug("  Needed change is merged")
            return True
        if not change.needs_change.is_current_patchset:
            self.log.debug("  Needed change is not the current patchset")
            return False
        if self.isChangeAlreadyInQueue(change.needs_change):
            self.log.debug("  Needed change is already ahead in the queue")
            return True
        if self.pipeline.trigger.canMerge(change.needs_change,
                                          self.getSubmitAllowNeeds()):
            self.log.debug("  Change %s is needed" %
                           change.needs_change)
            return change.needs_change
        # The needed change can't be merged.
        self.log.debug("  Change %s is needed but can not be merged" %
                       change.needs_change)
        return False
