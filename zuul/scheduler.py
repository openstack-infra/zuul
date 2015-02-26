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

import extras
import json
import logging
import os
import pickle
from six.moves import queue as Queue
import re
import sys
import threading
import time
import yaml

import layoutvalidator
import model
from model import ActionReporter, Pipeline, Project, ChangeQueue
from model import EventFilter, ChangeishFilter
from zuul import change_matcher
from zuul import version as zuul_version

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


class ManagementEvent(object):
    """An event that should be processed within the main queue run loop"""
    def __init__(self):
        self._wait_event = threading.Event()
        self._exception = None
        self._traceback = None

    def exception(self, e, tb):
        self._exception = e
        self._traceback = tb
        self._wait_event.set()

    def done(self):
        self._wait_event.set()

    def wait(self, timeout=None):
        self._wait_event.wait(timeout)
        if self._exception:
            raise self._exception, None, self._traceback
        return self._wait_event.is_set()


class ReconfigureEvent(ManagementEvent):
    """Reconfigure the scheduler.  The layout will be (re-)loaded from
    the path specified in the configuration.

    :arg ConfigParser config: the new configuration
    """
    def __init__(self, config):
        super(ReconfigureEvent, self).__init__()
        self.config = config


class PromoteEvent(ManagementEvent):
    """Promote one or more changes to the head of the queue.

    :arg str pipeline_name: the name of the pipeline
    :arg list change_ids: a list of strings of change ids in the form
        1234,1
    """

    def __init__(self, pipeline_name, change_ids):
        super(PromoteEvent, self).__init__()
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
    :arg str zuul_url: The URL of the Zuul Merger.
    :arg bool merged: Whether the merge succeeded (changes with refs).
    :arg bool updated: Whether the repo was updated (changes without refs).
    :arg str commit: The SHA of the merged commit (changes with refs).
    """

    def __init__(self, build_set, zuul_url, merged, updated, commit):
        self.build_set = build_set
        self.zuul_url = zuul_url
        self.merged = merged
        self.updated = updated
        self.commit = commit


def toList(item):
    if not item:
        return []
    if isinstance(item, list):
        return item
    return [item]


class Scheduler(threading.Thread):
    log = logging.getLogger("zuul.Scheduler")

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.wake_event = threading.Event()
        self.layout_lock = threading.Lock()
        self.run_handler_lock = threading.Lock()
        self._pause = False
        self._exit = False
        self._stopped = False
        self.launcher = None
        self.merger = None
        self.triggers = dict()
        self.reporters = dict()
        self.config = None

        self.trigger_event_queue = Queue.Queue()
        self.result_event_queue = Queue.Queue()
        self.management_event_queue = Queue.Queue()
        self.layout = model.Layout()

        self.zuul_version = zuul_version.version_info.version_string()
        self.last_reconfigured = None

    def stop(self):
        self._stopped = True
        self.wake_event.set()

    def testConfig(self, config_path):
        return self._parseConfig(config_path)

    def _parseSkipIf(self, config_job):
        cm = change_matcher
        skip_matchers = []

        for config_skip in config_job.get('skip-if', []):
            nested_matchers = []

            project_regex = config_skip.get('project')
            if project_regex:
                nested_matchers.append(cm.ProjectMatcher(project_regex))

            branch_regex = config_skip.get('branch')
            if branch_regex:
                nested_matchers.append(cm.BranchMatcher(branch_regex))

            file_regexes = toList(config_skip.get('all-files-match-any'))
            if file_regexes:
                file_matchers = [cm.FileMatcher(x) for x in file_regexes]
                all_files_matcher = cm.MatchAllFiles(file_matchers)
                nested_matchers.append(all_files_matcher)

            # All patterns need to match a given skip-if predicate
            skip_matchers.append(cm.MatchAll(nested_matchers))

        if skip_matchers:
            # Any skip-if predicate can be matched to trigger a skip
            return cm.MatchAny(skip_matchers)

    def _parseConfig(self, config_path):
        layout = model.Layout()
        project_templates = {}

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
                    base = os.path.dirname(os.path.realpath(config_path))
                    fn = os.path.join(base, fn)
                fn = os.path.expanduser(fn)
                execfile(fn, config_env)

        for conf_pipeline in data.get('pipelines', []):
            pipeline = Pipeline(conf_pipeline['name'])
            pipeline.description = conf_pipeline.get('description')
            # TODO(jeblair): remove backwards compatibility:
            pipeline.source = self.triggers[conf_pipeline.get('source',
                                                              'gerrit')]
            precedence = model.PRECEDENCE_MAP[conf_pipeline.get('precedence')]
            pipeline.precedence = precedence
            pipeline.failure_message = conf_pipeline.get('failure-message',
                                                         "Build failed.")
            pipeline.merge_failure_message = conf_pipeline.get(
                'merge-failure-message', "Merge Failed.\n\nThis change was "
                "unable to be automatically merged with the current state of "
                "the repository. Please rebase your change and upload a new "
                "patchset.")
            pipeline.success_message = conf_pipeline.get('success-message',
                                                         "Build succeeded.")
            pipeline.footer_message = conf_pipeline.get('footer-message', "")
            pipeline.dequeue_on_new_patchset = conf_pipeline.get(
                'dequeue-on-new-patchset', True)
            pipeline.ignore_dependencies = conf_pipeline.get(
                'ignore-dependencies', False)

            action_reporters = {}
            for action in ['start', 'success', 'failure', 'merge-failure']:
                action_reporters[action] = []
                if conf_pipeline.get(action):
                    for reporter_name, params \
                        in conf_pipeline.get(action).items():
                        if reporter_name in self.reporters.keys():
                            action_reporters[action].append(ActionReporter(
                                self.reporters[reporter_name], params))
                        else:
                            self.log.error('Invalid reporter name %s' %
                                           reporter_name)
            pipeline.start_actions = action_reporters['start']
            pipeline.success_actions = action_reporters['success']
            pipeline.failure_actions = action_reporters['failure']
            if len(action_reporters['merge-failure']) > 0:
                pipeline.merge_failure_actions = \
                    action_reporters['merge-failure']
            else:
                pipeline.merge_failure_actions = action_reporters['failure']

            pipeline.window = conf_pipeline.get('window', 20)
            pipeline.window_floor = conf_pipeline.get('window-floor', 3)
            pipeline.window_increase_type = conf_pipeline.get(
                'window-increase-type', 'linear')
            pipeline.window_increase_factor = conf_pipeline.get(
                'window-increase-factor', 1)
            pipeline.window_decrease_type = conf_pipeline.get(
                'window-decrease-type', 'exponential')
            pipeline.window_decrease_factor = conf_pipeline.get(
                'window-decrease-factor', 2)

            manager = globals()[conf_pipeline['manager']](self, pipeline)
            pipeline.setManager(manager)
            layout.pipelines[conf_pipeline['name']] = pipeline

            if 'require' in conf_pipeline:
                require = conf_pipeline['require']
                f = ChangeishFilter(
                    open=require.get('open'),
                    current_patchset=require.get('current-patchset'),
                    statuses=toList(require.get('status')),
                    required_approvals=toList(require.get('approval')))
                manager.changeish_filters.append(f)

            # TODO: move this into triggers (may require pluggable
            # configuration)
            if 'gerrit' in conf_pipeline['trigger']:
                for trigger in toList(conf_pipeline['trigger']['gerrit']):
                    approvals = {}
                    for approval_dict in toList(trigger.get('approval')):
                        for k, v in approval_dict.items():
                            approvals[k] = v
                    # Backwards compat for *_filter versions of these args
                    comments = toList(trigger.get('comment'))
                    if not comments:
                        comments = toList(trigger.get('comment_filter'))
                    emails = toList(trigger.get('email'))
                    if not emails:
                        emails = toList(trigger.get('email_filter'))
                    usernames = toList(trigger.get('username'))
                    if not usernames:
                        usernames = toList(trigger.get('username_filter'))
                    f = EventFilter(
                        trigger=self.triggers['gerrit'],
                        types=toList(trigger['event']),
                        branches=toList(trigger.get('branch')),
                        refs=toList(trigger.get('ref')),
                        event_approvals=approvals,
                        comments=comments,
                        emails=emails,
                        usernames=usernames,
                        required_approvals=toList(
                            trigger.get('require-approval')
                        )
                    )
                    manager.event_filters.append(f)
            if 'timer' in conf_pipeline['trigger']:
                for trigger in toList(conf_pipeline['trigger']['timer']):
                    f = EventFilter(trigger=self.triggers['timer'],
                                    types=['timer'],
                                    timespecs=toList(trigger['time']))
                    manager.event_filters.append(f)
            if 'zuul' in conf_pipeline['trigger']:
                for trigger in toList(conf_pipeline['trigger']['zuul']):
                    f = EventFilter(
                        trigger=self.triggers['zuul'],
                        types=toList(trigger['event']),
                        pipelines=toList(trigger.get('pipeline')),
                        required_approvals=toList(
                            trigger.get('require-approval')
                        )
                    )
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
            m = config_job.get('queue-name', None)
            if m:
                job.queue_name = m
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
            skip_if_matcher = self._parseSkipIf(config_job)
            if skip_if_matcher:
                job.skip_if_matcher = skip_if_matcher
            swift = toList(config_job.get('swift'))
            if swift:
                for s in swift:
                    job.swift[s['name']] = s

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
            shortname = config_project['name'].split('/')[-1]

            # This is reversed due to the prepend operation below, so
            # the ultimate order is templates (in order) followed by
            # statically defined jobs.
            for requested_template in reversed(
                config_project.get('template', [])):
                # Fetch the template from 'project-templates'
                tpl = project_templates.get(
                    requested_template.get('name'))
                # Expand it with the project context
                requested_template['name'] = shortname
                expanded = deep_format(tpl, requested_template)
                # Finally merge the expansion with whatever has been
                # already defined for this project.  Prepend our new
                # jobs to existing ones (which may have been
                # statically defined or defined by other templates).
                for pipeline in layout.pipelines.values():
                    if pipeline.name in expanded:
                        config_project.update(
                            {pipeline.name: expanded[pipeline.name] +
                             config_project.get(pipeline.name, [])})
            # TODO: future enhancement -- handle the case where
            # duplicate jobs have different children and you want all
            # of the children to run after a single run of the
            # parent).

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

    def setLauncher(self, launcher):
        self.launcher = launcher

    def setMerger(self, merger):
        self.merger = merger

    def registerTrigger(self, trigger, name=None):
        if name is None:
            name = trigger.name
        self.triggers[name] = trigger

    def registerReporter(self, reporter, name=None):
        if name is None:
            name = reporter.name
        self.reporters[name] = reporter

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
        event = BuildStartedEvent(build)
        self.result_event_queue.put(event)
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
        event = BuildCompletedEvent(build)
        self.result_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Done adding complete event for build: %s" % build)

    def onMergeCompleted(self, build_set, zuul_url, merged, updated, commit):
        self.log.debug("Adding merge complete event for build set: %s" %
                       build_set)
        event = MergeCompletedEvent(build_set, zuul_url,
                                    merged, updated, commit)
        self.result_event_queue.put(event)
        self.wake_event.set()

    def reconfigure(self, config):
        self.log.debug("Prepare to reconfigure")
        event = ReconfigureEvent(config)
        self.management_event_queue.put(event)
        self.wake_event.set()
        self.log.debug("Waiting for reconfiguration")
        event.wait()
        self.log.debug("Reconfiguration complete")
        self.last_reconfigured = int(time.time())

    def promote(self, pipeline_name, change_ids):
        event = PromoteEvent(pipeline_name, change_ids)
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

    def _doReconfigureEvent(self, event):
        # This is called in the scheduler loop after another thread submits
        # a request
        self.layout_lock.acquire()
        self.config = event.config
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
                self.log.debug("Re-enqueueing changes for pipeline %s" % name)
                items_to_remove = []
                builds_to_remove = []
                last_head = None
                for shared_queue in old_pipeline.queues:
                    for item in shared_queue.queue:
                        if not item.item_ahead:
                            last_head = item
                        item.item_ahead = None
                        item.items_behind = []
                        item.pipeline = None
                        item.queue = None
                        project = layout.projects.get(item.change.project.name)
                        if not project:
                            self.log.warning("Unable to find project for "
                                             "change %s while reenqueueing" %
                                             item.change)
                            item.change.project = None
                            items_to_remove.append(item)
                            continue
                        item.change.project = project
                        for build in item.current_build_set.getBuilds():
                            job = layout.jobs.get(build.job.name)
                            if job:
                                build.job = job
                            else:
                                builds_to_remove.append(build)
                        if not new_pipeline.manager.reEnqueueItem(item,
                                                                  last_head):
                            items_to_remove.append(item)
                for item in items_to_remove:
                    for build in item.current_build_set.getBuilds():
                        builds_to_remove.append(build)
                for build in builds_to_remove:
                    self.log.warning(
                        "Canceling build %s during reconfiguration" % (build,))
                    try:
                        self.launcher.cancel(build)
                    except Exception:
                        self.log.exception(
                            "Exception while canceling build %s "
                            "for change %s" % (build, item.change))
            self.layout = layout
            self.maintainTriggerCache()
            for trigger in self.triggers.values():
                trigger.postConfig()
            if statsd:
                try:
                    for pipeline in self.layout.pipelines.values():
                        items = len(pipeline.getAllItems())
                        # stats.gauges.zuul.pipeline.NAME.current_changes
                        key = 'zuul.pipeline.%s' % pipeline.name
                        statsd.gauge(key + '.current_changes', items)
                except Exception:
                    self.log.exception("Exception reporting initial "
                                       "pipeline stats:")
        finally:
            self.layout_lock.release()

    def _doPromoteEvent(self, event):
        pipeline = self.layout.pipelines[event.pipeline_name]
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
        project = self.layout.projects.get(event.project_name)
        pipeline = self.layout.pipelines[event.forced_pipeline]
        change = pipeline.source.getChange(event, project)
        self.log.debug("Event %s for change %s was directly assigned "
                       "to pipeline %s" % (event, change, self))
        self.log.info("Adding %s, %s to %s" %
                      (project, change, pipeline))
        pipeline.manager.addChange(change, ignore_requirements=True)

    def _areAllBuildsComplete(self):
        self.log.debug("Checking if all builds are complete")
        waiting = False
        if self.merger.areMergesOutstanding():
            waiting = True
        for pipeline in self.layout.pipelines.values():
            for item in pipeline.getAllItems():
                for build in item.current_build_set.getBuilds():
                    if build.result is None:
                        self.log.debug("%s waiting on %s" %
                                       (pipeline.manager, build))
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
                self.log.debug("Run handler stopping")
                return
            self.log.debug("Run handler awake")
            self.run_handler_lock.acquire()
            try:
                while not self.management_event_queue.empty():
                    self.process_management_queue()

                # Give result events priority -- they let us stop builds,
                # whereas trigger evensts cause us to launch builds.
                while not self.result_event_queue.empty():
                    self.process_result_queue()

                if not self._pause:
                    while not self.trigger_event_queue.empty():
                        self.process_event_queue()

                if self._pause and self._areAllBuildsComplete():
                    self._doPauseEvent()

                for pipeline in self.layout.pipelines.values():
                    while pipeline.manager.processQueue():
                        pass

            except Exception:
                self.log.exception("Exception in run handler:")
                # There may still be more events to process
                self.wake_event.set()
            finally:
                self.run_handler_lock.release()

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
        try:
            project = self.layout.projects.get(event.project_name)
            if not project:
                self.log.debug("Project %s not found" % event.project_name)
                return

            for pipeline in self.layout.pipelines.values():
                change = pipeline.source.getChange(event, project)
                if event.type == 'patchset-created':
                    pipeline.manager.removeOldVersionsOfChange(change)
                elif event.type == 'change-abandoned':
                    pipeline.manager.removeAbandonedChange(change)
                if pipeline.manager.eventMatches(event, change):
                    self.log.info("Adding %s, %s to %s" %
                                  (project, change, pipeline))
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
            elif isinstance(event, PromoteEvent):
                self._doPromoteEvent(event)
            elif isinstance(event, EnqueueEvent):
                self._doEnqueueEvent(event.trigger_event)
            else:
                self.log.error("Unable to handle event %s" % event)
            event.done()
        except Exception as e:
            event.exception(e, sys.exc_info()[2])
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
        pipeline.manager.onBuildStarted(event.build)

    def _doBuildCompletedEvent(self, event):
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

    def formatStatusJSON(self):
        data = {}

        data['zuul_version'] = self.zuul_version

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

        if self.last_reconfigured:
            data['last_reconfigured'] = self.last_reconfigured * 1000

        pipelines = []
        data['pipelines'] = pipelines
        for pipeline in self.layout.pipelines.values():
            pipelines.append(pipeline.formatStatusJSON())
        return json.dumps(data)


class BasePipelineManager(object):
    log = logging.getLogger("zuul.BasePipelineManager")

    def __init__(self, sched, pipeline):
        self.sched = sched
        self.pipeline = pipeline
        self.event_filters = []
        self.changeish_filters = []
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
        self.log.info("  Source: %s" % self.pipeline.source)
        self.log.info("  Requirements:")
        for f in self.changeish_filters:
            self.log.info("    %s" % f)
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
                if tree.job.skip_if_matcher:
                    efilters += str(tree.job.skip_if_matcher)
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
        self.log.info("  On start:")
        self.log.info("    %s" % self.pipeline.start_actions)
        self.log.info("  On success:")
        self.log.info("    %s" % self.pipeline.success_actions)
        self.log.info("  On failure:")
        self.log.info("    %s" % self.pipeline.failure_actions)
        self.log.info("  On merge-failure:")
        self.log.info("    %s" % self.pipeline.merge_failure_actions)

    def getSubmitAllowNeeds(self):
        # Get a list of code review labels that are allowed to be
        # "needed" in the submit records for a change, with respect
        # to this queue.  In other words, the list of review labels
        # this queue itself is likely to set before submitting.
        allow_needs = set()
        for action_reporter in self.pipeline.success_actions:
            allow_needs.update(action_reporter.getSubmitAllowNeeds())
        return allow_needs

    def eventMatches(self, event, change):
        if event.forced_pipeline:
            if event.forced_pipeline == self.pipeline.name:
                self.log.debug("Event %s for change %s was directly assigned "
                               "to pipeline %s" % (event, change, self))
                return True
            else:
                return False
        for ef in self.event_filters:
            if ef.matches(event, change):
                self.log.debug("Event %s for change %s matched %s "
                               "in pipeline %s" % (event, change, ef, self))
                return True
        return False

    def isChangeAlreadyInPipeline(self, change):
        # Checks live items in the pipeline
        for item in self.pipeline.getAllItems():
            if item.live and change.equals(item.change):
                return True
        return False

    def isChangeAlreadyInQueue(self, change, change_queue):
        # Checks any item in the specified change queue
        for item in change_queue.queue:
            if change.equals(item.change):
                return True
        return False

    def reportStart(self, change):
        try:
            self.log.info("Reporting start, action %s change %s" %
                          (self.pipeline.start_actions, change))
            msg = "Starting %s jobs." % self.pipeline.name
            if self.sched.config.has_option('zuul', 'status_url'):
                msg += "\n" + self.sched.config.get('zuul', 'status_url')
            ret = self.sendReport(self.pipeline.start_actions,
                                  change, msg)
            if ret:
                self.log.error("Reporting change start %s received: %s" %
                               (change, ret))
        except:
            self.log.exception("Exception while reporting start:")

    def sendReport(self, action_reporters, change, message):
        """Sends the built message off to configured reporters.

        Takes the action_reporters, change, message and extra options and
        sends them to the pluggable reporters.
        """
        report_errors = []
        if len(action_reporters) > 0:
            for action_reporter in action_reporters:
                ret = action_reporter.report(change, message)
                if ret:
                    report_errors.append(ret)
            if len(report_errors) == 0:
                return
        return report_errors

    def isChangeReadyToBeEnqueued(self, change):
        return True

    def enqueueChangesAhead(self, change, quiet, ignore_requirements,
                            change_queue):
        return True

    def enqueueChangesBehind(self, change, quiet, ignore_requirements,
                             change_queue):
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        return True

    def getFailingDependentItems(self, item):
        return None

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

    def getItemForChange(self, change):
        for item in self.pipeline.getAllItems():
            if item.change.equals(change):
                return item
        return None

    def findOldVersionOfChangeAlreadyInQueue(self, change):
        for item in self.pipeline.getAllItems():
            if not item.live:
                continue
            if change.isUpdateOf(item.change):
                return item
        return None

    def removeOldVersionsOfChange(self, change):
        if not self.pipeline.dequeue_on_new_patchset:
            return
        old_item = self.findOldVersionOfChangeAlreadyInQueue(change)
        if old_item:
            self.log.debug("Change %s is a new version of %s, removing %s" %
                           (change, old_item.change, old_item))
            self.removeItem(old_item)

    def removeAbandonedChange(self, change):
        self.log.debug("Change %s abandoned, removing." % change)
        for item in self.pipeline.getAllItems():
            if not item.live:
                continue
            if item.change.equals(change):
                self.removeItem(item)

    def reEnqueueItem(self, item, last_head):
        with self.getChangeQueue(item.change, last_head.queue) as change_queue:
            if change_queue:
                self.log.debug("Re-enqueing change %s in queue %s" %
                               (item.change, change_queue))
                change_queue.enqueueItem(item)
                self.reportStats(item)
                return True
            else:
                self.log.error("Unable to find change queue for project %s" %
                               item.change.project)
                return False

    def addChange(self, change, quiet=False, enqueue_time=None,
                  ignore_requirements=False, live=True,
                  change_queue=None):
        self.log.debug("Considering adding change %s" % change)

        # If we are adding a live change, check if it's a live item
        # anywhere in the pipeline.  Otherwise, we will perform the
        # duplicate check below on the specific change_queue.
        if live and self.isChangeAlreadyInPipeline(change):
            self.log.debug("Change %s is already in pipeline, "
                           "ignoring" % change)
            return True

        if not self.isChangeReadyToBeEnqueued(change):
            self.log.debug("Change %s is not ready to be enqueued, ignoring" %
                           change)
            return False

        if not ignore_requirements:
            for f in self.changeish_filters:
                if not f.matches(change):
                    self.log.debug("Change %s does not match pipeline "
                                   "requirement %s" % (change, f))
                    return False

        with self.getChangeQueue(change, change_queue) as change_queue:
            if not change_queue:
                self.log.debug("Unable to find change queue for "
                               "change %s in project %s" %
                               (change, change.project))
                return False

            if not self.enqueueChangesAhead(change, quiet, ignore_requirements,
                                            change_queue):
                self.log.debug("Failed to enqueue changes "
                               "ahead of %s" % change)
                return False

            if self.isChangeAlreadyInQueue(change, change_queue):
                self.log.debug("Change %s is already in queue, "
                               "ignoring" % change)
                return True

            self.log.debug("Adding change %s to queue %s" %
                           (change, change_queue))
            if not quiet:
                if len(self.pipeline.start_actions) > 0:
                    self.reportStart(change)
            item = change_queue.enqueueChange(change)
            if enqueue_time:
                item.enqueue_time = enqueue_time
            item.live = live
            self.reportStats(item)
            self.enqueueChangesBehind(change, quiet, ignore_requirements,
                                      change_queue)
            self.sched.triggers['zuul'].onChangeEnqueued(item.change,
                                                         self.pipeline)
            return True

    def dequeueItem(self, item):
        self.log.debug("Removing change %s from queue" % item.change)
        item.queue.dequeueItem(item)

    def removeItem(self, item):
        # Remove an item from the queue, probably because it has been
        # superseded by another change.
        self.log.debug("Canceling builds behind change: %s "
                       "because it is being removed." % item.change)
        self.cancelJobs(item)
        self.dequeueItem(item)
        self.reportStats(item)

    def _makeMergerItem(self, item):
        # Create a dictionary with all info about the item needed by
        # the merger.
        number = None
        patchset = None
        oldrev = None
        newrev = None
        if hasattr(item.change, 'number'):
            number = item.change.number
            patchset = item.change.patchset
        elif hasattr(item.change, 'newrev'):
            oldrev = item.change.oldrev
            newrev = item.change.newrev
        return dict(project=item.change.project.name,
                    url=self.pipeline.source.getGitUrl(
                        item.change.project),
                    merge_mode=item.change.project.merge_mode,
                    refspec=item.change.refspec,
                    branch=item.change.branch,
                    ref=item.current_build_set.ref,
                    number=number,
                    patchset=patchset,
                    oldrev=oldrev,
                    newrev=newrev,
                    )

    def prepareRef(self, item):
        # Returns True if the ref is ready, false otherwise
        build_set = item.current_build_set
        if build_set.merge_state == build_set.COMPLETE:
            return True
        if build_set.merge_state == build_set.PENDING:
            return False
        build_set.merge_state = build_set.PENDING
        ref = build_set.ref
        if hasattr(item.change, 'refspec') and not ref:
            self.log.debug("Preparing ref for: %s" % item.change)
            item.current_build_set.setConfiguration()
            dependent_items = self.getDependentItems(item)
            dependent_items.reverse()
            all_items = dependent_items + [item]
            merger_items = map(self._makeMergerItem, all_items)
            self.sched.merger.mergeChanges(merger_items,
                                           item.current_build_set,
                                           self.pipeline.precedence)
        else:
            self.log.debug("Preparing update repo for: %s" % item.change)
            url = self.pipeline.source.getGitUrl(item.change.project)
            self.sched.merger.updateRepo(item.change.project.name,
                                         url, build_set,
                                         self.pipeline.precedence)
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
        old_build_set = item.current_build_set
        if prime and item.current_build_set.ref:
            item.resetAllBuilds()
        for build in old_build_set.getBuilds():
            try:
                self.sched.launcher.cancel(build)
            except:
                self.log.exception("Exception while canceling build %s "
                                   "for change %s" % (build, item.change))
            build.result = 'CANCELED'
            canceled = True
        for item_behind in item.items_behind:
            self.log.debug("Canceling jobs for change %s, behind change %s" %
                           (item_behind.change, item.change))
            if self.cancelJobs(item_behind, prime=prime):
                canceled = True
        return canceled

    def _processOneItem(self, item, nnfi, ready_ahead):
        changed = False
        item_ahead = item.item_ahead
        if item_ahead and (not item_ahead.live):
            item_ahead = None
        change_queue = item.queue
        failing_reasons = []  # Reasons this item is failing

        if self.checkForChangesNeededBy(item.change, change_queue) is not True:
            # It's not okay to enqueue this change, we should remove it.
            self.log.info("Dequeuing change %s because "
                          "it can no longer merge" % item.change)
            self.cancelJobs(item)
            self.dequeueItem(item)
            self.pipeline.setDequeuedNeedingChange(item)
            if item.live:
                try:
                    self.reportItem(item)
                except MergeFailure:
                    pass
            return (True, nnfi, ready_ahead)
        dep_items = self.getFailingDependentItems(item)
        actionable = change_queue.isActionable(item)
        item.active = actionable
        ready = False
        if dep_items:
            failing_reasons.append('a needed change is failing')
            self.cancelJobs(item, prime=False)
        else:
            item_ahead_merged = False
            if (item_ahead and item_ahead.change.is_merged):
                item_ahead_merged = True
            if (item_ahead != nnfi and not item_ahead_merged):
                # Our current base is different than what we expected,
                # and it's not because our current base merged.  Something
                # ahead must have failed.
                self.log.info("Resetting builds for change %s because the "
                              "item ahead, %s, is not the nearest non-failing "
                              "item, %s" % (item.change, item_ahead, nnfi))
                change_queue.moveItem(item, nnfi)
                changed = True
                self.cancelJobs(item)
            if actionable:
                ready = self.prepareRef(item)
                if item.current_build_set.unable_to_merge:
                    failing_reasons.append("it has a merge conflict")
                    ready = False
        if not ready:
            ready_ahead = False
        if actionable and ready_ahead and self.launchJobs(item):
            changed = True
        if self.pipeline.didAnyJobFail(item):
            failing_reasons.append("at least one job failed")
        if (not item.live) and (not item.items_behind):
            failing_reasons.append("is a non-live item with no items behind")
            self.dequeueItem(item)
            changed = True
        if ((not item_ahead) and self.pipeline.areAllJobsComplete(item)
            and item.live):
            try:
                self.reportItem(item)
            except MergeFailure:
                failing_reasons.append("it did not merge")
                for item_behind in item.items_behind:
                    self.log.info("Resetting builds for change %s because the "
                                  "item ahead, %s, failed to merge" %
                                  (item_behind.change, item))
                    self.cancelJobs(item_behind)
            self.dequeueItem(item)
            changed = True
        elif not failing_reasons and item.live:
            nnfi = item
        item.current_build_set.failing_reasons = failing_reasons
        if failing_reasons:
            self.log.debug("%s is a failing item because %s" %
                           (item, failing_reasons))
        return (changed, nnfi, ready_ahead)

    def processQueue(self):
        # Do whatever needs to be done for each change in the queue
        self.log.debug("Starting queue processor: %s" % self.pipeline.name)
        changed = False
        for queue in self.pipeline.queues:
            queue_changed = False
            nnfi = None  # Nearest non-failing item
            ready_ahead = True  # All build sets ahead are ready
            for item in queue.queue[:]:
                item_changed, nnfi, ready_ahhead = self._processOneItem(
                    item, nnfi, ready_ahead)
                if item_changed:
                    queue_changed = True
                self.reportStats(item)
            if queue_changed:
                changed = True
                status = ''
                for item in queue.queue:
                    status += item.formatStatus()
                if status:
                    self.log.debug("Queue %s status is now:\n %s" %
                                   (queue.name, status))
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
        self.log.debug("Build %s started" % build)
        self.updateBuildDescriptions(build.build_set)
        return True

    def onBuildCompleted(self, build):
        self.log.debug("Build %s completed" % build)
        item = build.build_set.item

        self.pipeline.setResult(item, build)
        self.log.debug("Item %s status is now:\n %s" %
                       (item, item.formatStatus()))
        self.updateBuildDescriptions(build.build_set)
        return True

    def onMergeCompleted(self, event):
        build_set = event.build_set
        item = build_set.item
        build_set.merge_state = build_set.COMPLETE
        build_set.zuul_url = event.zuul_url
        if event.merged:
            build_set.commit = event.commit
        elif event.updated:
            build_set.commit = item.change.newrev
        if not build_set.commit:
            self.log.info("Unable to merge change %s" % item.change)
            self.pipeline.setUnableToMerge(item)

    def reportItem(self, item):
        if not item.reported:
            # _reportItem() returns True if it failed to report.
            item.reported = not self._reportItem(item)
        if self.changes_merge:
            succeeded = self.pipeline.didAllJobsSucceed(item)
            merged = item.reported
            if merged:
                merged = self.pipeline.source.isMerged(item.change,
                                                       item.change.branch)
            self.log.info("Reported change %s status: all-succeeded: %s, "
                          "merged: %s" % (item.change, succeeded, merged))
            change_queue = item.queue
            if not (succeeded and merged):
                self.log.debug("Reported change %s failed tests or failed "
                               "to merge" % (item.change))
                change_queue.decreaseWindowSize()
                self.log.debug("%s window size decreased to %s" %
                               (change_queue, change_queue.window))
                raise MergeFailure("Change %s failed to merge" % item.change)
            else:
                change_queue.increaseWindowSize()
                self.log.debug("%s window size increased to %s" %
                               (change_queue, change_queue.window))
                self.sched.triggers['zuul'].onChangeMerged(item.change)

    def _reportItem(self, item):
        self.log.debug("Reporting change %s" % item.change)
        ret = True  # Means error as returned by trigger.report
        if self.pipeline.didAllJobsSucceed(item):
            self.log.debug("success %s" % (self.pipeline.success_actions))
            actions = self.pipeline.success_actions
            item.setReportedResult('SUCCESS')
        elif not self.pipeline.didMergerSucceed(item):
            actions = self.pipeline.merge_failure_actions
            item.setReportedResult('MERGER_FAILURE')
        else:
            actions = self.pipeline.failure_actions
            item.setReportedResult('FAILURE')
        if actions:
            report = self.formatReport(item)
            try:
                self.log.info("Reporting change %s, actions: %s" %
                              (item.change, actions))
                ret = self.sendReport(actions, item.change, report)
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

        if item.dequeued_needing_change:
            ret += 'This change depends on a change that failed to merge.\n'
        elif not self.pipeline.didMergerSucceed(item):
            ret += self.pipeline.merge_failure_message
        else:
            if self.pipeline.didAllJobsSucceed(item):
                ret += self.pipeline.success_message + '\n\n'
            else:
                ret += self.pipeline.failure_message + '\n\n'
            ret += self._formatReportJobs(item)

        if self.pipeline.footer_message:
            ret += '\n' + self.pipeline.footer_message

        return ret

    def _formatReportJobs(self, item):
        # Return the list of jobs portion of the report
        ret = ''

        if self.sched.config.has_option('zuul', 'url_pattern'):
            url_pattern = self.sched.config.get('zuul', 'url_pattern')
        else:
            url_pattern = None

        for job in self.pipeline.getJobs(item):
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


class DynamicChangeQueueContextManager(object):
    def __init__(self, change_queue):
        self.change_queue = change_queue

    def __enter__(self):
        return self.change_queue

    def __exit__(self, etype, value, tb):
        if self.change_queue and not self.change_queue.queue:
            self.change_queue.pipeline.removeQueue(self.change_queue.queue)


class IndependentPipelineManager(BasePipelineManager):
    log = logging.getLogger("zuul.IndependentPipelineManager")
    changes_merge = False

    def _postConfig(self, layout):
        super(IndependentPipelineManager, self)._postConfig(layout)

    def getChangeQueue(self, change, existing=None):
        # creates a new change queue for every change
        if existing:
            return DynamicChangeQueueContextManager(existing)
        if change.project not in self.pipeline.getProjects():
            return DynamicChangeQueueContextManager(None)
        change_queue = ChangeQueue(self.pipeline)
        change_queue.addProject(change.project)
        self.pipeline.addQueue(change_queue)
        return DynamicChangeQueueContextManager(change_queue)

    def enqueueChangesAhead(self, change, quiet, ignore_requirements,
                            change_queue):
        ret = self.checkForChangesNeededBy(change, change_queue)
        if ret in [True, False]:
            return ret
        self.log.debug("  Changes %s must be merged ahead of %s" %
                       (ret, change))
        for needed_change in ret:
            # This differs from the dependent pipeline by enqueuing
            # changes ahead as "not live", that is, not intended to
            # have jobs run.  Also, pipeline requirements are always
            # ignored (which is safe because the changes are not
            # live).
            r = self.addChange(needed_change, quiet=True,
                               ignore_requirements=True,
                               live=False, change_queue=change_queue)
            if not r:
                return False
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        if self.pipeline.ignore_dependencies:
            return True
        self.log.debug("Checking for changes needed by %s:" % change)
        # Return true if okay to proceed enqueing this change,
        # false if the change should not be enqueued.
        if not hasattr(change, 'needs_changes'):
            self.log.debug("  Changeish does not support dependencies")
            return True
        if not change.needs_changes:
            self.log.debug("  No changes needed")
            return True
        changes_needed = []
        for needed_change in change.needs_changes:
            self.log.debug("  Change %s needs change %s:" % (
                change, needed_change))
            if needed_change.is_merged:
                self.log.debug("  Needed change is merged")
                continue
            if self.isChangeAlreadyInQueue(needed_change, change_queue):
                self.log.debug("  Needed change is already ahead in the queue")
                continue
            self.log.debug("  Change %s is needed" % needed_change)
            if needed_change not in changes_needed:
                changes_needed.append(needed_change)
                continue
            # This differs from the dependent pipeline check in not
            # verifying that the dependent change is mergable.
        if changes_needed:
            return changes_needed
        return True

    def dequeueItem(self, item):
        super(IndependentPipelineManager, self).dequeueItem(item)
        # An independent pipeline manager dynamically removes empty
        # queues
        if not item.queue.queue:
            self.pipeline.removeQueue(item.queue)


class StaticChangeQueueContextManager(object):
    def __init__(self, change_queue):
        self.change_queue = change_queue

    def __enter__(self):
        return self.change_queue

    def __exit__(self, etype, value, tb):
        pass


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
            change_queue = ChangeQueue(
                self.pipeline,
                window=self.pipeline.window,
                window_floor=self.pipeline.window_floor,
                window_increase_type=self.pipeline.window_increase_type,
                window_increase_factor=self.pipeline.window_increase_factor,
                window_decrease_type=self.pipeline.window_decrease_type,
                window_decrease_factor=self.pipeline.window_decrease_factor)
            change_queue.addProject(project)
            change_queues.append(change_queue)
            self.log.debug("Created queue: %s" % change_queue)

        # Iterate over all queues trying to combine them, and keep doing
        # so until they can not be combined further.
        last_change_queues = change_queues
        while True:
            new_change_queues = self.combineChangeQueues(last_change_queues)
            if len(last_change_queues) == len(new_change_queues):
                break
            last_change_queues = new_change_queues

        self.log.info("  Shared change queues:")
        for queue in new_change_queues:
            self.pipeline.addQueue(queue)
            self.log.info("    %s containing %s" % (
                queue, queue.generated_name))

    def combineChangeQueues(self, change_queues):
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
        return new_change_queues

    def getChangeQueue(self, change, existing=None):
        if existing:
            return StaticChangeQueueContextManager(existing)
        return StaticChangeQueueContextManager(
            self.pipeline.getQueue(change.project))

    def isChangeReadyToBeEnqueued(self, change):
        if not self.pipeline.source.canMerge(change,
                                             self.getSubmitAllowNeeds()):
            self.log.debug("Change %s can not merge, ignoring" % change)
            return False
        return True

    def enqueueChangesBehind(self, change, quiet, ignore_requirements,
                             change_queue):
        to_enqueue = []
        self.log.debug("Checking for changes needing %s:" % change)
        if not hasattr(change, 'needed_by_changes'):
            self.log.debug("  Changeish does not support dependencies")
            return
        for other_change in change.needed_by_changes:
            with self.getChangeQueue(other_change) as other_change_queue:
                if other_change_queue != change_queue:
                    self.log.debug("  Change %s in project %s can not be "
                                   "enqueued in the target queue %s" %
                                   (other_change, other_change.project,
                                    change_queue))
                    continue
            if self.pipeline.source.canMerge(other_change,
                                             self.getSubmitAllowNeeds()):
                self.log.debug("  Change %s needs %s and is ready to merge" %
                               (other_change, change))
                to_enqueue.append(other_change)

        if not to_enqueue:
            self.log.debug("  No changes need %s" % change)

        for other_change in to_enqueue:
            self.addChange(other_change, quiet=quiet,
                           ignore_requirements=ignore_requirements,
                           change_queue=change_queue)

    def enqueueChangesAhead(self, change, quiet, ignore_requirements,
                            change_queue):
        ret = self.checkForChangesNeededBy(change, change_queue)
        if ret in [True, False]:
            return ret
        self.log.debug("  Changes %s must be merged ahead of %s" %
                       (ret, change))
        for needed_change in ret:
            r = self.addChange(needed_change, quiet=quiet,
                               ignore_requirements=ignore_requirements,
                               change_queue=change_queue)
            if not r:
                return False
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        self.log.debug("Checking for changes needed by %s:" % change)
        # Return true if okay to proceed enqueing this change,
        # false if the change should not be enqueued.
        if not hasattr(change, 'needs_changes'):
            self.log.debug("  Changeish does not support dependencies")
            return True
        if not change.needs_changes:
            self.log.debug("  No changes needed")
            return True
        changes_needed = []
        # Ignore supplied change_queue
        with self.getChangeQueue(change) as change_queue:
            for needed_change in change.needs_changes:
                self.log.debug("  Change %s needs change %s:" % (
                    change, needed_change))
                if needed_change.is_merged:
                    self.log.debug("  Needed change is merged")
                    continue
                with self.getChangeQueue(needed_change) as needed_change_queue:
                    if needed_change_queue != change_queue:
                        self.log.debug("  Change %s in project %s does not "
                                       "share a change queue with %s "
                                       "in project %s" %
                                       (needed_change, needed_change.project,
                                        change, change.project))
                        return False
                if not needed_change.is_current_patchset:
                    self.log.debug("  Needed change is not the "
                                   "current patchset")
                    return False
                if self.isChangeAlreadyInQueue(needed_change, change_queue):
                    self.log.debug("  Needed change is already ahead "
                                   "in the queue")
                    continue
                if self.pipeline.source.canMerge(needed_change,
                                                 self.getSubmitAllowNeeds()):
                    self.log.debug("  Change %s is needed" % needed_change)
                    if needed_change not in changes_needed:
                        changes_needed.append(needed_change)
                        continue
                # The needed change can't be merged.
                self.log.debug("  Change %s is needed but can not be merged" %
                               needed_change)
                return False
        if changes_needed:
            return changes_needed
        return True

    def getFailingDependentItems(self, item):
        if not hasattr(item.change, 'needs_changes'):
            return None
        if not item.change.needs_changes:
            return None
        failing_items = set()
        for needed_change in item.change.needs_changes:
            needed_item = self.getItemForChange(needed_change)
            if not needed_item:
                continue
            if needed_item.current_build_set.failing_reasons:
                failing_items.add(needed_item)
        if failing_items:
            return failing_items
        return None
