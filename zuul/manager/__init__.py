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
import textwrap
import urllib

from zuul import exceptions
from zuul import model
from zuul.lib.dependson import find_dependency_headers


class DynamicChangeQueueContextManager(object):
    def __init__(self, change_queue):
        self.change_queue = change_queue

    def __enter__(self):
        return self.change_queue

    def __exit__(self, etype, value, tb):
        if self.change_queue and not self.change_queue.queue:
            self.change_queue.pipeline.removeQueue(self.change_queue)


class StaticChangeQueueContextManager(object):
    def __init__(self, change_queue):
        self.change_queue = change_queue

    def __enter__(self):
        return self.change_queue

    def __exit__(self, etype, value, tb):
        pass


class PipelineManager(object):
    """Abstract Base Class for enqueing and processing Changes in a Pipeline"""

    def __init__(self, sched, pipeline):
        self.log = logging.getLogger("zuul.Pipeline.%s.%s" %
                                     (pipeline.tenant.name,
                                      pipeline.name,))
        self.sched = sched
        self.pipeline = pipeline
        self.event_filters = []
        self.ref_filters = []

    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self.pipeline.name)

    def _postConfig(self, layout):
        # All pipelines support shared queues for setting
        # relative_priority; only the dependent pipeline uses them for
        # pipeline queing.
        self.buildChangeQueues(layout)

    def buildChangeQueues(self, layout):
        self.log.debug("Building relative_priority queues")
        change_queues = self.pipeline.relative_priority_queues
        tenant = self.pipeline.tenant
        layout_project_configs = layout.project_configs

        for project_name, project_configs in layout_project_configs.items():
            (trusted, project) = tenant.getProject(project_name)
            queue_name = None
            project_in_pipeline = False
            for project_config in layout.getAllProjectConfigs(project_name):
                project_pipeline_config = project_config.pipelines.get(
                    self.pipeline.name)
                if project_pipeline_config is None:
                    continue
                project_in_pipeline = True
                queue_name = project_pipeline_config.queue_name
                if queue_name:
                    break
            if not project_in_pipeline:
                continue
            if not queue_name:
                continue
            if queue_name in change_queues:
                change_queue = change_queues[queue_name]
            else:
                change_queue = []
                change_queues[queue_name] = change_queue
                self.log.debug("Created queue: %s" % queue_name)
            change_queue.append(project)
            self.log.debug("Added project %s to queue: %s" %
                           (project, queue_name))

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

    def getNodePriority(self, item):
        queue = self.pipeline.getRelativePriorityQueue(item.change.project)
        items = self.pipeline.getAllItems()
        items = [i for i in items
                 if i.change.project in queue and
                 i.live]
        return items.index(item)

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

    def reportStart(self, item):
        if not self.pipeline._disabled:
            self.log.info("Reporting start, action %s item %s" %
                          (self.pipeline.start_actions, item))
            ret = self.sendReport(self.pipeline.start_actions, item)
            if ret:
                self.log.error("Reporting item start %s received: %s" %
                               (item, ret))

    def sendReport(self, action_reporters, item, message=None):
        """Sends the built message off to configured reporters.

        Takes the action_reporters, item, message and extra options and
        sends them to the pluggable reporters.
        """
        report_errors = []
        if len(action_reporters) > 0:
            for reporter in action_reporters:
                try:
                    ret = reporter.report(item)
                    if ret:
                        report_errors.append(ret)
                except Exception as e:
                    item.setReportedResult('ERROR')
                    self.log.exception("Exception while reporting")
                    report_errors.append(str(e))
        return report_errors

    def isChangeReadyToBeEnqueued(self, change):
        return True

    def enqueueChangesAhead(self, change, quiet, ignore_requirements,
                            change_queue, history=None):
        return True

    def enqueueChangesBehind(self, change, quiet, ignore_requirements,
                             change_queue):
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        return True

    def getFailingDependentItems(self, item):
        return None

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

    def reEnqueueItem(self, item, last_head, old_item_ahead, item_ahead_valid):
        with self.getChangeQueue(item.change, last_head.queue) as change_queue:
            if change_queue:
                self.log.debug("Re-enqueing change %s in queue %s" %
                               (item.change, change_queue))
                change_queue.enqueueItem(item)

                # If the old item ahead was re-enqued, this value will
                # be true, so we should attempt to move the item back
                # to where it was in case an item ahead is already
                # failing.
                if item_ahead_valid:
                    change_queue.moveItem(item, old_item_ahead)
                # Get an updated copy of the layout and update the job
                # graph if necessary.  This resumes the buildset merge
                # state machine.  If we have an up-to-date layout, it
                # will go ahead and refresh the job graph if needed;
                # or it will send a new merge job if necessary, or it
                # will do nothing if we're waiting on a merge job.
                item.job_graph = None
                item.layout = None
                if item.active:
                    if self.prepareItem(item):
                        self.prepareJobs(item)

                # Re-set build results in case any new jobs have been
                # added to the tree.
                for build in item.current_build_set.getBuilds():
                    if build.result:
                        item.setResult(build)
                # Similarly, reset the item state.
                if item.current_build_set.unable_to_merge:
                    item.setUnableToMerge()
                if item.current_build_set.config_errors:
                    item.setConfigErrors(item.current_build_set.config_errors)
                if item.dequeued_needing_change:
                    item.setDequeuedNeedingChange()

                self.reportStats(item)
                return True
            else:
                self.log.error("Unable to find change queue for project %s" %
                               item.change.project)
                return False

    def addChange(self, change, quiet=False, enqueue_time=None,
                  ignore_requirements=False, live=True,
                  change_queue=None, history=None):
        self.log.debug("Considering adding change %s" % change)

        # If we are adding a live change, check if it's a live item
        # anywhere in the pipeline.  Otherwise, we will perform the
        # duplicate check below on the specific change_queue.
        if live and self.isChangeAlreadyInPipeline(change):
            self.log.debug("Change %s is already in pipeline, "
                           "ignoring" % change)
            return True

        if not ignore_requirements:
            for f in self.ref_filters:
                if f.connection_name != change.project.connection_name:
                    self.log.debug("Filter %s skipped for change %s due "
                                   "to mismatched connections" % (f, change))
                    continue
                if not f.matches(change):
                    self.log.debug("Change %s does not match pipeline "
                                   "requirement %s" % (change, f))
                    return False

        if not self.isChangeReadyToBeEnqueued(change):
            self.log.debug("Change %s is not ready to be enqueued, ignoring" %
                           change)
            return False

        with self.getChangeQueue(change, change_queue) as change_queue:
            if not change_queue:
                self.log.debug("Unable to find change queue for "
                               "change %s in project %s" %
                               (change, change.project))
                return False

            if not self.enqueueChangesAhead(change, quiet, ignore_requirements,
                                            change_queue, history=history):
                self.log.debug("Failed to enqueue changes "
                               "ahead of %s" % change)
                return False

            if self.isChangeAlreadyInQueue(change, change_queue):
                self.log.debug("Change %s is already in queue, "
                               "ignoring" % change)
                return True

            self.log.info("Adding change %s to queue %s in %s" %
                          (change, change_queue, self.pipeline))
            item = change_queue.enqueueChange(change)
            if enqueue_time:
                item.enqueue_time = enqueue_time
            item.live = live
            self.reportStats(item)
            item.quiet = quiet
            self.enqueueChangesBehind(change, quiet, ignore_requirements,
                                      change_queue)
            zuul_driver = self.sched.connections.drivers['zuul']
            tenant = self.pipeline.tenant
            zuul_driver.onChangeEnqueued(tenant, item.change, self.pipeline)
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

    def updateCommitDependencies(self, change, change_queue):
        # Search for Depends-On headers and find appropriate changes
        self.log.debug("  Updating commit dependencies for %s", change)
        change.refresh_deps = False
        dependencies = []
        seen = set()
        for match in find_dependency_headers(change.message):
            self.log.debug("  Found Depends-On header: %s", match)
            if match in seen:
                continue
            seen.add(match)
            try:
                url = urllib.parse.urlparse(match)
            except ValueError:
                continue
            source = self.sched.connections.getSourceByHostname(
                url.hostname)
            if not source:
                continue
            self.log.debug("  Found source: %s", source)
            dep = source.getChangeByURL(match)
            if dep and (not dep.is_merged) and dep not in dependencies:
                self.log.debug("  Adding dependency: %s", dep)
                dependencies.append(dep)
        change.commit_needs_changes = dependencies

    def provisionNodes(self, item):
        jobs = item.findJobsToRequest(item.pipeline.tenant.semaphore_handler)
        if not jobs:
            return False
        build_set = item.current_build_set
        self.log.debug("Requesting nodes for change %s" % item.change)
        if self.sched.use_relative_priority:
            priority = item.getNodePriority()
        else:
            priority = 0
        for job in jobs:
            req = self.sched.nodepool.requestNodes(build_set, job, priority)
            self.log.debug("Adding node request %s for job %s to item %s" %
                           (req, job, item))
            build_set.setJobNodeRequest(job.name, req)
        return True

    def _executeJobs(self, item, jobs):
        self.log.debug("Executing jobs for change %s" % item.change)
        build_set = item.current_build_set
        for job in jobs:
            self.log.debug("Found job %s for change %s" % (job, item.change))
            try:
                nodeset = item.current_build_set.getJobNodeSet(job.name)
                self.sched.nodepool.useNodeSet(nodeset)
                self.sched.executor.execute(
                    job, item, self.pipeline,
                    build_set.dependent_changes,
                    build_set.merger_items)
            except Exception:
                self.log.exception("Exception while executing job %s "
                                   "for change %s:" % (job, item.change))
                try:
                    # If we hit an exception we don't have a build in the
                    # current item so a potentially aquired semaphore must be
                    # released as it won't be released on dequeue of the item.
                    tenant = item.pipeline.tenant
                    tenant.semaphore_handler.release(item, job)
                except Exception:
                    self.log.exception("Exception while releasing semaphore")

    def executeJobs(self, item):
        # TODO(jeblair): This should return a value indicating a job
        # was executed.  Appears to be a longstanding bug.
        if not item.layout:
            return False

        jobs = item.findJobsToRun(
            item.pipeline.tenant.semaphore_handler)
        if jobs:
            self._executeJobs(item, jobs)

    def cancelJobs(self, item, prime=True):
        self.log.debug("Cancel jobs for change %s" % item.change)
        canceled = False
        jobs_to_release = []

        old_build_set = item.current_build_set
        old_jobs = {job.name: job for job in item.getJobs()}

        if prime and item.current_build_set.ref:
            item.resetAllBuilds()
        for req in old_build_set.node_requests.values():
            self.sched.nodepool.cancelRequest(req)
            jobs_to_release.append(req.job)
        old_build_set.node_requests = {}
        canceled_jobs = set()
        for build in old_build_set.getBuilds():
            if build.result:
                canceled_jobs.add(build.job.name)
                continue
            was_running = False
            try:
                was_running = self.sched.executor.cancel(build)
            except Exception:
                self.log.exception("Exception while canceling build %s "
                                   "for change %s" % (build, item.change))
            jobs_to_release.append(build.job)

            if not was_running:
                nodeset = build.build_set.getJobNodeSet(build.job.name)
                self.sched.nodepool.returnNodeSet(nodeset, build)
            build.result = 'CANCELED'
            canceled = True
            canceled_jobs.add(build.job.name)
        for jobname, nodeset in list(old_build_set.nodesets.items()):
            if jobname in canceled_jobs:
                continue
            self.sched.nodepool.returnNodeSet(nodeset)
            jobs_to_release.append(old_jobs[jobname])

        for job in jobs_to_release:
            tenant = old_build_set.item.pipeline.tenant
            tenant.semaphore_handler.release(
                old_build_set.item, job)

        for item_behind in item.items_behind:
            self.log.debug("Canceling jobs for change %s, behind change %s" %
                           (item_behind.change, item.change))
            if self.cancelJobs(item_behind, prime=prime):
                canceled = True
        return canceled

    def _loadDynamicLayout(self, item):
        # Load layout
        # Late import to break an import loop
        import zuul.configloader
        loader = zuul.configloader.ConfigLoader(
            self.sched.connections, self.sched, None, None)

        self.log.debug("Loading dynamic layout")

        parent_layout = None
        parent = item.item_ahead
        while not parent_layout and parent:
            parent_layout = parent.layout
            parent = parent.item_ahead
        if not parent_layout:
            parent_layout = item.pipeline.tenant.layout

        (trusted_updates, untrusted_updates) = item.includesConfigUpdates()
        build_set = item.current_build_set
        trusted_layout_verified = False
        try:
            # First parse the config as it will land with the
            # full set of config and project repos.  This lets us
            # catch syntax errors in config repos even though we won't
            # actually run with that config.
            if trusted_updates:
                self.log.debug("Loading dynamic layout (phase 1)")
                layout = loader.createDynamicLayout(
                    item.pipeline.tenant,
                    build_set.files,
                    self.sched.ansible_manager,
                    include_config_projects=True)
                if not len(layout.loading_errors):
                    trusted_layout_verified = True

            # Then create the config a second time but without changes
            # to config repos so that we actually use this config.
            if untrusted_updates:
                self.log.debug("Loading dynamic layout (phase 2)")
                layout = loader.createDynamicLayout(
                    item.pipeline.tenant,
                    build_set.files,
                    self.sched.ansible_manager,
                    include_config_projects=False)
            else:
                # We're a change to a config repo (with no untrusted
                # config items ahead), so just use the current pipeline
                # layout.
                if not len(layout.loading_errors):
                    return item.queue.pipeline.tenant.layout
            if len(layout.loading_errors):
                self.log.info("Configuration syntax error in dynamic layout")
                if trusted_layout_verified:
                    # The config is good if we include config-projects,
                    # but is currently invalid if we omit them.  Instead
                    # of returning the whole error message, just leave a
                    # note that the config will work once the dependent
                    # changes land.
                    msg = "This change depends on a change "\
                          "to a config project.\n\n"
                    msg += textwrap.fill(textwrap.dedent("""\
                    The syntax of the configuration in this change has
                    been verified to be correct once the config project
                    change upon which it depends is merged, but it can not
                    be used until that occurs."""))
                    item.setConfigError(msg)
                    return None
                else:
                    # Find a layout loading error that match
                    # the current item.change and only report
                    # if one is found.
                    relevant_errors = []
                    for err in layout.loading_errors.errors:
                        econtext = err.key.context
                        if ((err.key not in
                             parent_layout.loading_errors.error_keys) or
                            (econtext.project == item.change.project.name and
                             econtext.branch == item.change.branch)):
                            relevant_errors.append(err)
                    if relevant_errors:
                        item.setConfigErrors(relevant_errors)
                        return None
                    self.log.info(
                        "Configuration syntax error not related to "
                        "change context. Error won't be reported.")
            else:
                self.log.debug("Loading dynamic layout complete")
        except Exception:
            self.log.exception("Error in dynamic layout")
            item.setConfigError("Unknown configuration error")
            return None
        return layout

    def _queueUpdatesConfig(self, item):
        while item:
            if item.change.updatesConfig():
                return True
            item = item.item_ahead
        return False

    def getLayout(self, item):
        if not self._queueUpdatesConfig(item):
            # No config updates in queue. Use existing pipeline layout
            return item.queue.pipeline.tenant.layout
        elif (not item.change.updatesConfig() and
                item.item_ahead and item.item_ahead.live):
            # Current change does not update layout, use its parent if parent
            # has a layout.
            return item.item_ahead.layout
        # Else this item or a non live parent updates the config,
        # ask the merger for the result.
        build_set = item.current_build_set
        if build_set.merge_state == build_set.PENDING:
            return None
        if build_set.merge_state == build_set.COMPLETE:
            if build_set.unable_to_merge:
                return None
            self.log.debug("Preparing dynamic layout for: %s" % item.change)
            return self._loadDynamicLayout(item)

    def scheduleMerge(self, item, files=None, dirs=None):
        self.log.debug("Scheduling merge for item %s (files: %s, dirs: %s)" %
                       (item, files, dirs))
        build_set = item.current_build_set
        build_set.merge_state = build_set.PENDING
        if isinstance(item.change, model.Change):
            self.sched.merger.mergeChanges(build_set.merger_items,
                                           item.current_build_set, files, dirs,
                                           precedence=self.pipeline.precedence)
        else:
            self.sched.merger.getRepoState(build_set.merger_items,
                                           item.current_build_set,
                                           precedence=self.pipeline.precedence)
        return False

    def scheduleFilesChanges(self, item):
        self.log.debug("Scheduling fileschanged for item %s", item)
        build_set = item.current_build_set
        build_set.files_state = build_set.PENDING

        self.sched.merger.getFilesChanges(
            item.change.project.connection_name, item.change.project.name,
            item.change.ref, item.change.branch, build_set=build_set)
        return False

    def prepareItem(self, item):
        # This runs on every iteration of _processOneItem
        # Returns True if the item is ready, false otherwise
        ready = True
        build_set = item.current_build_set
        if not build_set.ref:
            build_set.setConfiguration()
        if build_set.merge_state == build_set.NEW:
            ready = self.scheduleMerge(item,
                                       files=['zuul.yaml', '.zuul.yaml'],
                                       dirs=['zuul.d', '.zuul.d'])
        if build_set.files_state == build_set.NEW:
            ready = self.scheduleFilesChanges(item)
        if build_set.files_state == build_set.PENDING:
            ready = False
        if build_set.merge_state == build_set.PENDING:
            ready = False
        if build_set.unable_to_merge:
            ready = False
        if build_set.config_errors:
            ready = False
        return ready

    def prepareJobs(self, item):
        # This only runs once the item is in the pipeline's action window
        # Returns True if the item is ready, false otherwise
        if not item.live:
            # Short circuit as non live items don't need layouts.
            # We also don't need to take further ready actions in
            # _processOneItem() so we return false.
            return False
        elif not item.layout:
            item.layout = self.getLayout(item)
        if not item.layout:
            return False

        if not item.job_graph:
            try:
                self.log.debug("Freezing job graph for %s" % (item,))
                item.freezeJobGraph()
            except Exception as e:
                # TODOv3(jeblair): nicify this exception as it will be reported
                self.log.exception("Error freezing job graph for %s" %
                                   (item,))
                item.setConfigError("Unable to freeze job graph: %s" %
                                    (str(e)))
                return False
        return True

    def _processOneItem(self, item, nnfi):
        changed = False
        ready = False
        dequeued = False
        failing_reasons = []  # Reasons this item is failing

        item_ahead = item.item_ahead
        if item_ahead and (not item_ahead.live):
            item_ahead = None
        change_queue = item.queue

        if self.checkForChangesNeededBy(item.change, change_queue) is not True:
            # It's not okay to enqueue this change, we should remove it.
            self.log.info("Dequeuing change %s because "
                          "it can no longer merge" % item.change)
            self.cancelJobs(item)
            self.dequeueItem(item)
            item.setDequeuedNeedingChange()
            if item.live:
                try:
                    self.reportItem(item)
                except exceptions.MergeFailure:
                    pass
            return (True, nnfi)

        actionable = change_queue.isActionable(item)
        item.active = actionable

        dep_items = self.getFailingDependentItems(item)
        if dep_items:
            failing_reasons.append('a needed change is failing')
            self.cancelJobs(item, prime=False)
        else:
            item_ahead_merged = False
            if (item_ahead and
                hasattr(item_ahead.change, 'is_merged') and
                item_ahead.change.is_merged):
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
            if actionable and item.live:
                ready = self.prepareItem(item) and self.prepareJobs(item)
                # Starting jobs reporting should only be done once if there are
                # jobs to run for this item.
                if ready and len(self.pipeline.start_actions) > 0 \
                        and len(item.job_graph.jobs) > 0 \
                        and not item.reported_start \
                        and not item.quiet:
                    self.reportStart(item)
                    item.reported_start = True
                if item.current_build_set.unable_to_merge:
                    failing_reasons.append("it has a merge conflict")
                if item.current_build_set.config_errors:
                    failing_reasons.append("it has an invalid configuration")
                if ready and self.provisionNodes(item):
                    changed = True
        if ready and self.executeJobs(item):
            changed = True

        if item.hasAnyJobFailed():
            failing_reasons.append("at least one job failed")
        if (not item.live) and (not item.items_behind) and (not dequeued):
            failing_reasons.append("is a non-live item with no items behind")
            self.dequeueItem(item)
            changed = dequeued = True
        if ((not item_ahead) and item.areAllJobsComplete() and item.live):
            try:
                self.reportItem(item)
            except exceptions.MergeFailure:
                failing_reasons.append("it did not merge")
                for item_behind in item.items_behind:
                    self.log.info("Resetting builds for change %s because the "
                                  "item ahead, %s, failed to merge" %
                                  (item_behind.change, item))
                    self.cancelJobs(item_behind)
            self.dequeueItem(item)
            changed = dequeued = True
        elif not failing_reasons and item.live:
            nnfi = item
        item.current_build_set.failing_reasons = failing_reasons
        if failing_reasons:
            self.log.debug("%s is a failing item because %s" %
                           (item, failing_reasons))
        if item.live and not dequeued and self.sched.use_relative_priority:
            priority = item.getNodePriority()
            for node_request in item.current_build_set.node_requests.values():
                if node_request.relative_priority != priority:
                    self.sched.nodepool.reviseRequest(
                        node_request, priority)
        return (changed, nnfi)

    def processQueue(self):
        # Do whatever needs to be done for each change in the queue
        self.log.debug("Starting queue processor: %s" % self.pipeline.name)
        changed = False
        for queue in self.pipeline.queues:
            queue_changed = False
            nnfi = None  # Nearest non-failing item
            for item in queue.queue[:]:
                item_changed, nnfi = self._processOneItem(
                    item, nnfi)
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

    def onBuildStarted(self, build):
        self.log.debug("Build %s started" % build)
        return True

    def onBuildPaused(self, build):
        item = build.build_set.item
        self.log.debug("Build %s of %s paused", build, item.change)
        item.setResult(build)

        # We need to resume builds because we could either have no children
        # or have children that are already skipped.
        self._resumeBuilds(build.build_set)
        return True

    def _resumeBuilds(self, build_set):
        """
        Resumes all paused builds of a buildset that may be resumed.
        """
        jobgraph = build_set.item.job_graph
        for build in build_set.builds.values():
            if not build.paused:
                continue
            # check if all child jobs are finished
            child_builds = [build_set.builds.get(x.name) for x in
                            jobgraph.getDependentJobsRecursively(
                                build.job.name)]
            all_completed = True
            for child_build in child_builds:
                if not child_build or not child_build.result:
                    all_completed = False
                    break

            if all_completed:
                self.sched.executor.resumeBuild(build)
                build.paused = False

    def onBuildCompleted(self, build):
        item = build.build_set.item

        self.log.debug("Build %s of %s completed" % (build, item.change))

        item.setResult(build)
        item.pipeline.tenant.semaphore_handler.release(item, build.job)
        self.log.debug("Item %s status is now:\n %s" %
                       (item, item.formatStatus()))

        if build.retry and build.build_set.getJobNodeSet(build.job.name):
            build.build_set.removeJobNodeSet(build.job.name)

        self._resumeBuilds(build.build_set)
        return True

    def onFilesChangesCompleted(self, event):
        build_set = event.build_set
        item = build_set.item
        item.change.files = event.files
        build_set.files_state = build_set.COMPLETE

    def onMergeCompleted(self, event):
        build_set = event.build_set
        item = build_set.item
        build_set.merge_state = build_set.COMPLETE
        build_set.repo_state = event.repo_state
        if event.merged:
            build_set.commit = event.commit
            items_ahead = item.getNonLiveItemsAhead()
            for index, item in enumerate(items_ahead):
                files = item.current_build_set.files
                files.setFiles(event.files[:index + 1])
            build_set.files.setFiles(event.files)
        elif event.updated:
            build_set.commit = (item.change.newrev or
                                '0000000000000000000000000000000000000000')
        if not build_set.commit:
            self.log.info("Unable to merge change %s" % item.change)
            item.setUnableToMerge()

    def onNodesProvisioned(self, event):
        # TODOv3(jeblair): handle provisioning failure here
        request = event.request
        build_set = request.build_set
        build_set.jobNodeRequestComplete(request.job.name, request,
                                         request.nodeset)
        if request.failed or not request.fulfilled:
            self.log.info("Node request %s: failure for %s" %
                          (request, request.job.name,))
            build_set.item.setNodeRequestFailure(request.job)
            self._resumeBuilds(request.build_set)
            tenant = build_set.item.pipeline.tenant
            tenant.semaphore_handler.release(build_set.item, request.job)

        self.log.info("Completed node request %s for job %s of item %s "
                      "with nodes %s" %
                      (request, request.job, build_set.item,
                       request.nodeset))

    def reportItem(self, item):
        if not item.reported:
            # _reportItem() returns True if it failed to report.
            item.reported = not self._reportItem(item)
        if self.changes_merge:
            succeeded = item.didAllJobsSucceed()
            merged = item.reported
            source = item.change.project.source
            if merged:
                merged = source.isMerged(item.change, item.change.branch)
            self.log.info("Reported change %s status: all-succeeded: %s, "
                          "merged: %s" % (item.change, succeeded, merged))
            change_queue = item.queue
            if not (succeeded and merged):
                self.log.debug("Reported change %s failed tests or failed "
                               "to merge" % (item.change))
                change_queue.decreaseWindowSize()
                self.log.debug("%s window size decreased to %s" %
                               (change_queue, change_queue.window))
                raise exceptions.MergeFailure(
                    "Change %s failed to merge" % item.change)
            else:
                change_queue.increaseWindowSize()
                self.log.debug("%s window size increased to %s" %
                               (change_queue, change_queue.window))

                zuul_driver = self.sched.connections.drivers['zuul']
                tenant = self.pipeline.tenant
                zuul_driver.onChangeMerged(tenant, item.change, source)

    def _reportItem(self, item):
        self.log.debug("Reporting change %s" % item.change)
        ret = True  # Means error as returned by trigger.report

        # In the case of failure, we may not hove completed an initial
        # merge which would get the layout for this item, so in order
        # to determine whether this item's project is in this
        # pipeline, use the dynamic layout if available, otherwise,
        # fall back to the current static layout as a best
        # approximation.
        layout = (item.layout or self.pipeline.tenant.layout)

        project_in_pipeline = True
        ppc = None
        try:
            ppc = layout.getProjectPipelineConfig(item)
        except Exception:
            self.log.exception("Invalid config for change %s" % item.change)
        if not ppc:
            self.log.debug("Project %s not in pipeline %s for change %s" % (
                item.change.project, self.pipeline, item.change))
            project_in_pipeline = False
            actions = []
        elif item.getConfigErrors():
            self.log.debug("Invalid config for change %s" % item.change)
            # TODOv3(jeblair): consider a new reporter action for this
            actions = self.pipeline.merge_failure_actions
            item.setReportedResult('CONFIG_ERROR')
        elif item.didMergerFail():
            actions = self.pipeline.merge_failure_actions
            item.setReportedResult('MERGER_FAILURE')
        elif item.wasDequeuedNeedingChange():
            actions = self.pipeline.failure_actions
            item.setReportedResult('FAILURE')
        elif not item.getJobs():
            # We don't send empty reports with +1
            self.log.debug("No jobs for change %s" % (item.change,))
            actions = []
        elif item.didAllJobsSucceed():
            self.log.debug("success %s" % (self.pipeline.success_actions))
            actions = self.pipeline.success_actions
            item.setReportedResult('SUCCESS')
            self.pipeline._consecutive_failures = 0
        else:
            actions = self.pipeline.failure_actions
            item.setReportedResult('FAILURE')
            self.pipeline._consecutive_failures += 1
        if project_in_pipeline and self.pipeline._disabled:
            actions = self.pipeline.disabled_actions
        # Check here if we should disable so that we only use the disabled
        # reporters /after/ the last disable_at failure is still reported as
        # normal.
        if (self.pipeline.disable_at and not self.pipeline._disabled and
            self.pipeline._consecutive_failures >= self.pipeline.disable_at):
            self.pipeline._disabled = True
        if actions:
            self.log.info("Reporting item %s, actions: %s" %
                          (item, actions))
            ret = self.sendReport(actions, item)
            if ret:
                self.log.error("Reporting item %s received: %s" %
                               (item, ret))
        return ret

    def reportStats(self, item):
        if not self.sched.statsd:
            return
        try:
            # Update the gauge on enqueue and dequeue, but timers only
            # when dequeing.
            if item.dequeue_time:
                dt = int((item.dequeue_time - item.enqueue_time) * 1000)
            else:
                dt = None
            items = len(self.pipeline.getAllItems())

            tenant = self.pipeline.tenant
            basekey = 'zuul.tenant.%s' % tenant.name
            key = '%s.pipeline.%s' % (basekey, self.pipeline.name)
            # stats.timers.zuul.tenant.<tenant>.pipeline.<pipeline>.resident_time
            # stats_counts.zuul.tenant.<tenant>.pipeline.<pipeline>.total_changes
            # stats.gauges.zuul.tenant.<tenant>.pipeline.<pipeline>.current_changes
            self.sched.statsd.gauge(key + '.current_changes', items)
            if dt:
                self.sched.statsd.timing(key + '.resident_time', dt)
                self.sched.statsd.incr(key + '.total_changes')
            if hasattr(item.change, 'branch'):
                hostname = (item.change.project.canonical_hostname.
                            replace('.', '_'))
                projectname = (item.change.project.name.
                               replace('.', '_').replace('/', '.'))
                projectname = projectname.replace('.', '_').replace('/', '.')
                branchname = item.change.branch.replace('.', '_').replace(
                    '/', '.')
                # stats.timers.zuul.tenant.<tenant>.pipeline.<pipeline>.
                #   project.<host>.<project>.<branch>.resident_time
                # stats_counts.zuul.tenant.<tenant>.pipeline.<pipeline>.
                #   project.<host>.<project>.<branch>.total_changes
                key += '.project.%s.%s.%s' % (hostname, projectname,
                                              branchname)
                if dt:
                    self.sched.statsd.timing(key + '.resident_time', dt)
                    self.sched.statsd.incr(key + '.total_changes')
        except Exception:
            self.log.exception("Exception reporting pipeline stats")
