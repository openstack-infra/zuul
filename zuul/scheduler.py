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

import logging
import os
import pickle
import Queue
import re
import threading
import yaml

import model
from model import Pipeline, Job, Project, ChangeQueue, EventFilter
import merger


class Scheduler(threading.Thread):
    log = logging.getLogger("zuul.Scheduler")

    def __init__(self):
        threading.Thread.__init__(self)
        self.wake_event = threading.Event()
        self.reconfigure_complete_event = threading.Event()
        self.queue_lock = threading.Lock()
        self._pause = False
        self._reconfigure = False
        self._exit = False
        self._stopped = False
        self.launcher = None
        self.trigger = None

        self.trigger_event_queue = Queue.Queue()
        self.result_event_queue = Queue.Queue()
        self._init()

    def _init(self):
        self.pipelines = {}
        self.jobs = {}
        self.projects = {}
        self.metajobs = {}

    def stop(self):
        self._stopped = True
        self.wake_event.set()

    def _parseConfig(self, config_path):
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

        self._config_env = {}
        for include in data.get('includes', []):
            if 'python-file' in include:
                fn = include['python-file']
                if not os.path.isabs(fn):
                    base = os.path.dirname(config_path)
                    fn = os.path.join(base, fn)
                fn = os.path.expanduser(fn)
                execfile(fn, self._config_env)

        for conf_pipeline in data.get('pipelines', []):
            pipeline = Pipeline(conf_pipeline['name'])
            manager = globals()[conf_pipeline['manager']](self, pipeline)
            pipeline.setManager(manager)

            self.pipelines[conf_pipeline['name']] = pipeline
            manager.success_action = conf_pipeline.get('success')
            manager.failure_action = conf_pipeline.get('failure')
            manager.start_action = conf_pipeline.get('start')
            for trigger in toList(conf_pipeline['trigger']):
                approvals = {}
                for approval_dict in toList(trigger.get('approval')):
                    for k, v in approval_dict.items():
                        approvals[k] = v
                f = EventFilter(types=toList(trigger['event']),
                                branches=toList(trigger.get('branch')),
                                refs=toList(trigger.get('ref')),
                                approvals=approvals,
                                comment_filters=
                                toList(trigger.get('comment_filter')))
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
            m = config_job.get('hold-following-changes', False)
            if m:
                job.hold_following_changes = True
            m = config_job.get('voting', None)
            if m is not None:
                job.voting = m
            fname = config_job.get('parameter-function', None)
            if fname:
                func = self._config_env.get(fname, None)
                if not func:
                    raise Exception("Unable to find function %s" % fname)
                job.parameter_function = func
            branches = toList(config_job.get('branch'))
            if branches:
                job._branches = branches
                job.branches = [re.compile(x) for x in branches]

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
            mode = config_project.get('merge-mode')
            if mode and mode == 'cherry-pick':
                project.merge_mode = model.CHERRY_PICK
            for pipeline in self.pipelines.values():
                if pipeline.name in config_project:
                    job_tree = pipeline.addProject(project)
                    config_jobs = config_project[pipeline.name]
                    add_jobs(job_tree, config_jobs)

        # All jobs should be defined at this point, get rid of
        # metajobs so that getJob isn't doing anything weird.
        self.metajobs = {}

        # TODO(jeblair): check that we don't end up with jobs like
        # "foo - bar" because a ':' is missing in the yaml for a dependent job
        for pipeline in self.pipelines.values():
            pipeline.manager._postConfig()

        if self.config.has_option('zuul', 'git_dir'):
            merge_root = self.config.get('zuul', 'git_dir')
        else:
            merge_root = '/var/lib/zuul/git'
        if self.config.has_option('zuul', 'push_change_refs'):
            push_refs = self.config.getboolean('zuul', 'push_change_refs')
        else:
            push_refs = False
        if self.config.has_option('gerrit', 'sshkey'):
            sshkey = self.config.get('gerrit', 'sshkey')
        else:
            sshkey = None
        self.merger = merger.Merger(self.trigger, merge_root, push_refs,
                                    sshkey)
        for project in self.projects.values():
            url = self.trigger.getGitUrl(project)
            self.merger.addProject(project, url)

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
        self.queue_lock.acquire()
        self.trigger_event_queue.put(event)
        self.queue_lock.release()
        self.wake_event.set()

    def onBuildStarted(self, build):
        self.log.debug("Adding start event for build: %s" % build)
        self.queue_lock.acquire()
        self.result_event_queue.put(('started', build))
        self.queue_lock.release()
        self.wake_event.set()

    def onBuildCompleted(self, build):
        self.log.debug("Adding complete event for build: %s" % build)
        self.queue_lock.acquire()
        self.result_event_queue.put(('completed', build))
        self.queue_lock.release()
        self.wake_event.set()

    def reconfigure(self, config):
        self.log.debug("Prepare to reconfigure")
        self.config = config
        self._pause = True
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
        if self._reconfigure:
            self.log.debug("Performing reconfiguration")
            self._init()
            self._parseConfig(self.config.get('zuul', 'layout_config'))
            self._pause = False
            self._reconfigure = False
            self.reconfigure_complete_event.set()

    def _areAllBuildsComplete(self):
        self.log.debug("Checking if all builds are complete")
        waiting = False
        for pipeline in self.pipelines.values():
            for build in pipeline.manager.building_jobs.keys():
                self.log.debug("%s waiting on %s" % (pipeline.manager, build))
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
            if self._stopped:
                return
            self.log.debug("Run handler awake")
            self.queue_lock.acquire()
            try:
                if not self._pause:
                    if not self.trigger_event_queue.empty():
                        self.process_event_queue()

                if not self.result_event_queue.empty():
                    self.process_result_queue()

                if self._pause and self._areAllBuildsComplete():
                    self._doPauseEvent()

                if not self._pause:
                    if not (self.trigger_event_queue.empty() and
                            self.result_event_queue.empty()):
                        self.wake_event.set()
                else:
                    if not self.result_event_queue.empty():
                        self.wake_event.set()
            except:
                self.log.exception("Exception in run handler:")
            self.queue_lock.release()

    def process_event_queue(self):
        self.log.debug("Fetching trigger event")
        event = self.trigger_event_queue.get()
        self.log.debug("Processing trigger event %s" % event)
        project = self.projects.get(event.project_name)
        if not project:
            self.log.warning("Project %s not found" % event.project_name)
            return

        for pipeline in self.pipelines.values():
            if not pipeline.manager.eventMatches(event):
                self.log.debug("Event %s ignored by %s" % (event, pipeline))
                continue
            change = event.getChange(project, self.trigger)
            self.log.info("Adding %s, %s to %s" %
                          (project, change, pipeline))
            pipeline.manager.addChange(change)

    def process_result_queue(self):
        self.log.debug("Fetching result event")
        event_type, build = self.result_event_queue.get()
        self.log.debug("Processing result event %s" % build)
        for pipeline in self.pipelines.values():
            if event_type == 'started':
                if pipeline.manager.onBuildStarted(build):
                    return
            elif event_type == 'completed':
                if pipeline.manager.onBuildCompleted(build):
                    return
        self.log.warning("Build %s not found by any queue manager" % (build))

    def formatStatusHTML(self):
        ret = '<html><pre>'
        if self._pause:
            ret += '<p><b>Queue only mode:</b> preparing to '
            if self._reconfigure:
                ret += 'reconfigure'
            if self._exit:
                ret += 'exit'
            ret += ', queue length: %s' % self.trigger_event_queue.qsize()
            ret += '</p>'

        keys = self.pipelines.keys()
        keys.sort()
        for key in keys:
            pipeline = self.pipelines[key]
            s = 'Pipeline: %s' % pipeline.name
            ret += s + '\n'
            ret += '-' * len(s) + '\n'
            ret += pipeline.formatStatusHTML()
            ret += '\n'
        ret += '</pre></html>'
        return ret


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

    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self.pipeline.name)

    def _postConfig(self):
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

        for p in self.sched.projects.values():
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
            ret = self.sched.trigger.report(change, msg, self.start_action)
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
            self.log.debug("Failed to enqueue changes ahead of" % change)
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
            change_queue.enqueueChange(change)
            self.enqueueChangesBehind(change)
        else:
            self.log.error("Unable to find change queue for project %s" %
                           change.project)
            return False
        self.launchJobs()

    def _launchJobs(self, change, jobs):
        self.log.debug("Launching jobs for change %s" % change)
        ref = change.current_build_set.ref
        if hasattr(change, 'refspec') and not ref:
            change.current_build_set.setConfiguration()
            ref = change.current_build_set.ref
            mode = model.MERGE_IF_NECESSARY
            commit = self.sched.merger.mergeChanges([change], ref, mode=mode)
            if not commit:
                self.log.info("Unable to merge change %s" % change)
                self.pipeline.setUnableToMerge(change)
                self.possiblyReportChange(change)
                return
            change.current_build_set.commit = commit
        for job in self.pipeline.findJobsToRun(change):
            self.log.debug("Found job %s for change %s" % (job, change))
            try:
                build = self.sched.launcher.launch(job, change, self.pipeline)
                self.building_jobs[build] = change
                self.log.debug("Adding build %s of job %s to change %s" %
                               (build, job, change))
                change.addBuild(build)
            except:
                self.log.exception("Exception while launching job %s "
                                   "for change %s:" % (job, change))

    def launchJobs(self, change=None):
        if not change:
            for change in self.pipeline.getAllChanges():
                self.launchJobs(change)
            return
        jobs = self.pipeline.findJobsToRun(change)
        if jobs:
            self._launchJobs(change, jobs)

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
        if build not in self.building_jobs:
            self.log.debug("Build %s not found" % (build))
            # Or triggered externally, or triggered before zuul started,
            # or restarted
            return False

        self.updateBuildDescriptions(build.build_set)
        return True

    def handleFailedChange(self, change):
        pass

    def onBuildCompleted(self, build):
        self.log.debug("Build %s completed" % build)
        if build not in self.building_jobs:
            self.log.debug("Build %s not found" % (build))
            # Or triggered externally, or triggered before zuul started,
            # or restarted
            return False
        change = self.building_jobs[build]
        self.log.debug("Found change %s which triggered completed build %s" %
                       (change, build))

        del self.building_jobs[build]

        self.pipeline.setResult(change, build)
        self.log.info("Change %s status is now:\n %s" %
                      (change, self.pipeline.formatStatus(change)))

        if self.pipeline.didAnyJobFail(change):
            self.handleFailedChange(change)

        self.reportChanges()
        self.launchJobs()
        self.updateBuildDescriptions(build.build_set)
        return True

    def reportChanges(self):
        self.log.debug("Searching for changes to report")
        reported = False
        for change in self.pipeline.getAllChanges():
            self.log.debug("  checking %s" % change)
            if self.pipeline.areAllJobsComplete(change):
                self.log.debug("  possibly reporting %s" % change)
                if self.possiblyReportChange(change):
                    reported = True
        if reported:
            self.reportChanges()
        self.log.debug("Done searching for changes to report")

    def possiblyReportChange(self, change):
        self.log.debug("Possibly reporting change %s" % change)
        # Even if a change isn't reportable, keep going so that it
        # gets dequeued in the normal manner.
        if change.is_reportable and change.reported:
            self.log.debug("Change %s already reported" % change)
            return False
        change_ahead = change.change_ahead
        if not change_ahead:
            self.log.debug("Change %s is at the front of the queue, "
                           "reporting" % (change))
            ret = self.reportChange(change)
            if self.changes_merge:
                succeeded = self.pipeline.didAllJobsSucceed(change)
                merged = (not ret)
                if merged:
                    merged = self.sched.trigger.isMerged(change, change.branch)
                self.log.info("Reported change %s status: all-succeeded: %s, "
                              "merged: %s" % (change, succeeded, merged))
                if not (succeeded and merged):
                    self.log.debug("Reported change %s failed tests or failed "
                                   "to merge" % (change))
                    self.handleFailedChange(change)
                    return True
            self.log.debug("Removing reported change %s from queue" %
                           change)
            change_queue = self.pipeline.getQueue(change.project)
            change_queue.dequeueChange(change)
            return True

    def reportChange(self, change):
        if not change.is_reportable:
            return False
        if change.reported:
            return 0
        self.log.debug("Reporting change %s" % change)
        ret = None
        if self.pipeline.didAllJobsSucceed(change):
            action = self.success_action
            change.setReportedResult('SUCCESS')
        else:
            action = self.failure_action
            change.setReportedResult('FAILURE')
        report = self.formatReport(change)
        change.reported = True
        try:
            self.log.info("Reporting change %s, action: %s" %
                          (change, action))
            ret = self.sched.trigger.report(change, report, action)
            if ret:
                self.log.error("Reporting change %s received: %s" %
                               (change, ret))
        except:
            self.log.exception("Exception while reporting:")
            change.setReportedResult('ERROR')
        self.updateBuildDescriptions(change.current_build_set)
        return ret

    def formatReport(self, changeish):
        ret = ''
        if self.pipeline.didAllJobsSucceed(changeish):
            ret += 'Build successful\n\n'
        else:
            ret += 'Build failed\n\n'

        if changeish.dequeued_needing_change:
            ret += "This change depends on a change that failed to merge."
        elif changeish.current_build_set.unable_to_merge:
            ret += "This change was unable to be automatically merged "\
                   "with the current state of the repository. Please "\
                   "rebase your change and upload a new patchset."
        else:
            if self.sched.config.has_option('zuul', 'url_pattern'):
                pattern = self.sched.config.get('zuul', 'url_pattern')
            else:
                pattern = None
            for job in self.pipeline.getJobs(changeish):
                build = changeish.current_build_set.getBuild(job.name)
                result = build.result
                if result == 'SUCCESS' and job.success_message:
                    result = job.success_message
                elif result == 'FAILURE' and job.failure_message:
                    result = job.failure_message
                url = None
                if build.url:
                    if pattern:
                        url = pattern.format(change=changeish,
                                             pipeline=self.pipeline,
                                             job=job,
                                             build=build)
                    else:
                        url = build.url
                if not url:
                    url = job.name
                if not job.voting:
                    voting = ' (non-voting)'
                else:
                    voting = ''
                ret += '- %s : %s%s\n' % (url, result, voting)
        return ret

    def formatDescription(self, build):
        concurrent_changes = ''
        concurrent_builds = ''
        other_builds = ''

        for change in build.build_set.other_changes:
            concurrent_changes += '<li><a href="{change.url}">\
              {change.number},{change.patchset}</a></li>'.format(
                change=change)

        change = build.build_set.change

        for build in build.build_set.getBuilds():
            if build.base_url:
                concurrent_builds += """\
<li>
  <a href="{build.base_url}">
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
  Preceded by: <a href="{build.base_url}">
  {build.job.name} #{build.number}</a>
</li>
""".format(build=other_build)

        if build.build_set.next_build_set:
            other_build = build.build_set.next_build_set.getBuild(
                build.job.name)
            if other_build:
                other_builds += """\
<li>
  Succeeded by: <a href="{build.base_url}">
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
        else:
            ret = """\
<p>
  Triggered by reference:
    {change.ref}</a><br/>
  Old revision: <b>{change.oldrev}</b><br/>
  New revision: <b>{change.newrev}</b><br/>
  Pipeline: <b>{self.pipeline.name}</b>
</p>"""

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


class IndependentPipelineManager(BasePipelineManager):
    log = logging.getLogger("zuul.IndependentPipelineManager")
    changes_merge = False

    def _postConfig(self):
        super(IndependentPipelineManager, self)._postConfig()

        change_queue = ChangeQueue(self.pipeline, dependent=False)
        for project in self.pipeline.getProjects():
            change_queue.addProject(project)

        self.pipeline.addQueue(change_queue)


class DependentPipelineManager(BasePipelineManager):
    log = logging.getLogger("zuul.DependentPipelineManager")
    changes_merge = True

    def __init__(self, *args, **kwargs):
        super(DependentPipelineManager, self).__init__(*args, **kwargs)

    def _postConfig(self):
        super(DependentPipelineManager, self)._postConfig()
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
        if not self.sched.trigger.canMerge(change,
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
            if self.sched.trigger.canMerge(needs,
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
        if self.sched.trigger.canMerge(change.needs_change,
                                       self.getSubmitAllowNeeds()):
            self.log.debug("  Change %s is needed" %
                           change.needs_change)
            return change.needs_change
        # The needed change can't be merged.
        self.log.debug("  Change %s is needed but can not be merged" %
                       change.needs_change)
        return False

    def _getDependentChanges(self, change):
        orig_change = change
        changes = []
        while change.change_ahead:
            changes.append(change.change_ahead)
            change = change.change_ahead
        self.log.info("Change %s depends on changes %s" % (orig_change,
                                                           changes))
        return changes

    def _launchJobs(self, change, jobs):
        self.log.debug("Launching jobs for change %s" % change)
        ref = change.current_build_set.ref
        if hasattr(change, 'refspec') and not ref:
            change.current_build_set.setConfiguration()
            ref = change.current_build_set.ref
            dependent_changes = self._getDependentChanges(change)
            dependent_changes.reverse()
            all_changes = dependent_changes + [change]
            commit = self.sched.merger.mergeChanges(all_changes, ref)
            if not commit:
                self.log.info("Unable to merge changes %s" % all_changes)
                self.pipeline.setUnableToMerge(change)
                self.possiblyReportChange(change)
                return
            change.current_build_set.commit = commit
        #TODO: remove this line after GERRIT_CHANGES is gone
        dependent_changes = self._getDependentChanges(change)
        for job in jobs:
            self.log.debug("Found job %s for change %s" % (job, change))
            try:
                #TODO: remove dependent_changes after GERRIT_CHANGES is gone
                build = self.sched.launcher.launch(job, change, self.pipeline,
                                                   dependent_changes)
                self.building_jobs[build] = change
                self.log.debug("Adding build %s of job %s to change %s" %
                               (build, job, change))
                change.addBuild(build)
            except:
                self.log.exception("Exception while launching job %s "
                                   "for change %s:" % (job, change))

    def cancelJobs(self, change, prime=True):
        self.log.debug("Cancel jobs for change %s" % change)
        to_remove = []
        if prime:
            change.resetAllBuilds()
        for build, build_change in self.building_jobs.items():
            if build_change == change:
                self.log.debug("Found build %s for change %s to cancel" %
                               (build, change))
                try:
                    self.sched.launcher.cancel(build)
                except:
                    self.log.exception("Exception while canceling build %s "
                                       "for change %s" % (build, change))
                to_remove.append(build)
        for build in to_remove:
            self.log.debug("Removing build %s from running builds" % build)
            build.result = 'CANCELED'
            del self.building_jobs[build]
        if change.change_behind:
            self.log.debug("Canceling jobs for change %s, behind change %s" %
                           (change.change_behind, change))
            self.cancelJobs(change.change_behind, prime=prime)

    def handleFailedChange(self, change):
        # A build failed. All changes behind this change will need to
        # be retested. To free up resources cancel the builds behind
        # this one as they will be rerun anyways.
        change_ahead = change.change_ahead
        change_behind = change.change_behind
        if not change_ahead:
            # If we're at the head of the queue, allow changes to relaunch
            if change_behind:
                self.log.info("Canceling/relaunching jobs for change %s "
                              "behind failed change %s" %
                              (change_behind, change))
                self.cancelJobs(change_behind)
            self.dequeueChange(change)
        elif change_behind:
            self.log.debug("Canceling builds behind change: %s due to "
                           "failure." % change)
            self.cancelJobs(change_behind, prime=False)

    def dequeueChange(self, change):
        self.log.debug("Removing change %s from queue" % change)
        change_ahead = change.change_ahead
        change_behind = change.change_behind
        change_queue = self.pipeline.getQueue(change.project)
        change_queue.dequeueChange(change)
        if not change_ahead and not change.reported:
            self.log.debug("Adding %s as a severed head" % change)
            change_queue.addSeveredHead(change)
        self.dequeueDependentChanges(change_behind)

    def dequeueDependentChanges(self, change):
        # When a change is dequeued after failing, dequeue any changes that
        # depend on it.
        while change:
            change_behind = change.change_behind
            if self.checkForChangesNeededBy(change) is not True:
                # It's not okay to enqueue this change, we should remove it.
                self.log.info("Dequeuing change %s because "
                              "it can no longer merge" % change)
                change_queue = self.pipeline.getQueue(change.project)
                change_queue.dequeueChange(change)
                self.pipeline.setDequeuedNeedingChange(change)
                self.reportChange(change)
                # We don't need to recurse, because any changes that might
                # be affected by the removal of this change are behind us
                # in the queue, so we can continue walking backwards.
            change = change_behind
