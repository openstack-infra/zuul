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
import logging

from zuul import exceptions
from zuul.model import NullChange

statsd = extras.try_import('statsd.statsd')


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


class BasePipelineManager(object):
    log = logging.getLogger("zuul.BasePipelineManager")

    def __init__(self, sched, pipeline):
        self.sched = sched
        self.pipeline = pipeline
        self.event_filters = []
        self.changeish_filters = []

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
                tags = []
                if tree.job.hold_following_changes:
                    tags.append('[hold]')
                if not tree.job.voting:
                    tags.append('[nonvoting]')
                if tree.job.mutex:
                    tags.append('[mutex: %s]' % tree.job.mutex)
                tags = ' '.join(tags)
                self.log.info("%s%s%s %s" % (istr, repr(tree.job),
                                             efilters, tags))
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
        self.log.info("  When disabled:")
        self.log.info("    %s" % self.pipeline.disabled_actions)

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

    def reportStart(self, item):
        if not self.pipeline._disabled:
            try:
                self.log.info("Reporting start, action %s item %s" %
                              (self.pipeline.start_actions, item))
                ret = self.sendReport(self.pipeline.start_actions,
                                      self.pipeline.source, item)
                if ret:
                    self.log.error("Reporting item start %s received: %s" %
                                   (item, ret))
            except:
                self.log.exception("Exception while reporting start:")

    def sendReport(self, action_reporters, source, item,
                   message=None):
        """Sends the built message off to configured reporters.

        Takes the action_reporters, item, message and extra options and
        sends them to the pluggable reporters.
        """
        report_errors = []
        if len(action_reporters) > 0:
            for reporter in action_reporters:
                ret = reporter.report(source, self.pipeline, item)
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

                # Re-set build results in case any new jobs have been
                # added to the tree.
                for build in item.current_build_set.getBuilds():
                    if build.result:
                        self.pipeline.setResult(item, build)
                # Similarly, reset the item state.
                if item.current_build_set.unable_to_merge:
                    self.pipeline.setUnableToMerge(item)
                if item.dequeued_needing_change:
                    self.pipeline.setDequeuedNeedingChange(item)

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
            item = change_queue.enqueueChange(change)
            if enqueue_time:
                item.enqueue_time = enqueue_time
            item.live = live
            self.reportStats(item)
            if not quiet:
                if len(self.pipeline.start_actions) > 0:
                    self.reportStart(item)
            self.enqueueChangesBehind(change, quiet, ignore_requirements,
                                      change_queue)
            for trigger in self.sched.triggers.values():
                trigger.onChangeEnqueued(item.change, self.pipeline)
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

    def provisionNodes(self, item):
        jobs = self.pipeline.findJobsToRequest(item)
        if not jobs:
            return False
        build_set = item.current_build_set
        self.log.debug("Requesting nodes for change %s" % item.change)
        for job in jobs:
            req = self.sched.nodepool.requestNodes(build_set, job)
            self.log.debug("Adding node request %s for job %s to item %s" %
                           (req, job, item))
            build_set.setJobNodeRequest(job.name, req)
        return True

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
        # TODO(jeblair): This should return a value indicating a job
        # was launched.  Appears to be a longstanding bug.
        jobs = self.pipeline.findJobsToRun(item, self.sched.mutex)
        if jobs:
            self._launchJobs(item, jobs)

    def cancelJobs(self, item, prime=True):
        self.log.debug("Cancel jobs for change %s" % item.change)
        canceled = False
        old_build_set = item.current_build_set
        if prime and item.current_build_set.ref:
            item.resetAllBuilds()
        for req in old_build_set.node_requests.values():
            self.sched.nodepool.cancelRequest(req)
        old_build_set.node_requests = {}
        for build in old_build_set.getBuilds():
            try:
                self.sched.launcher.cancel(build)
            except:
                self.log.exception("Exception while canceling build %s "
                                   "for change %s" % (build, item.change))
            build.result = 'CANCELED'
            canceled = True
        self.updateBuildDescriptions(old_build_set)
        for item_behind in item.items_behind:
            self.log.debug("Canceling jobs for change %s, behind change %s" %
                           (item_behind.change, item.change))
            if self.cancelJobs(item_behind, prime=prime):
                canceled = True
        return canceled

    def _processOneItem(self, item, nnfi):
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
                except exceptions.MergeFailure:
                    pass
            return (True, nnfi)
        dep_items = self.getFailingDependentItems(item)
        actionable = change_queue.isActionable(item)
        item.active = actionable
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
            if not item.current_build_set.ref:
                item.current_build_set.setConfiguration()
            if self.provisionNodes(item):
                changed = True
            if self.launchJobs(item):
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
            except exceptions.MergeFailure:
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

    def updateBuildDescriptions(self, build_set):
        for build in build_set.getBuilds():
            try:
                desc = self.formatDescription(build)
                self.sched.launcher.setBuildDescription(build, desc)
            except:
                # Log the failure and let loop continue
                self.log.error("Failed to update description for build %s" %
                               (build))

        if build_set.previous_build_set:
            for build in build_set.previous_build_set.getBuilds():
                try:
                    desc = self.formatDescription(build)
                    self.sched.launcher.setBuildDescription(build, desc)
                except:
                    # Log the failure and let loop continue
                    self.log.error("Failed to update description for "
                                   "build %s in previous build set" % (build))

    def onBuildStarted(self, build):
        self.log.debug("Build %s started" % build)
        return True

    def onBuildCompleted(self, build):
        self.log.debug("Build %s completed" % build)
        item = build.build_set.item

        self.pipeline.setResult(item, build)
        self.sched.mutex.release(item, build.job)
        self.log.debug("Item %s status is now:\n %s" %
                       (item, item.formatStatus()))
        return True

    def onMergeCompleted(self, event):
        build_set = event.build_set
        item = build_set.item
        build_set.merge_state = build_set.COMPLETE
        build_set.zuul_url = event.zuul_url
        if event.merged:
            build_set.commit = event.commit
        elif event.updated:
            if not isinstance(item.change, NullChange):
                build_set.commit = item.change.newrev
        if not build_set.commit and not isinstance(item.change, NullChange):
            self.log.info("Unable to merge change %s" % item.change)
            self.pipeline.setUnableToMerge(item)

    def onNodesProvisioned(self, event):
        request = event.request
        build_set = request.build_set
        build_set.jobNodeRequestComplete(request.job.name, request,
                                         request.nodes)
        self.log.info("Completed node request %s for job %s of item %s" %
                      (request, request.job.name, build_set.item))

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
                raise exceptions.MergeFailure(
                    "Change %s failed to merge" % item.change)
            else:
                change_queue.increaseWindowSize()
                self.log.debug("%s window size increased to %s" %
                               (change_queue, change_queue.window))

                for trigger in self.sched.triggers.values():
                    trigger.onChangeMerged(item.change, self.pipeline.source)

    def _reportItem(self, item):
        self.log.debug("Reporting change %s" % item.change)
        ret = True  # Means error as returned by trigger.report
        if not self.pipeline.getJobs(item):
            # We don't send empty reports with +1,
            # and the same for -1's (merge failures or transient errors)
            # as they cannot be followed by +1's
            self.log.debug("No jobs for change %s" % item.change)
            actions = []
        elif self.pipeline.didAllJobsSucceed(item):
            self.log.debug("success %s" % (self.pipeline.success_actions))
            actions = self.pipeline.success_actions
            item.setReportedResult('SUCCESS')
            self.pipeline._consecutive_failures = 0
        else:
            actions = self.pipeline.failure_actions
            item.setReportedResult('FAILURE')
            self.pipeline._consecutive_failures += 1
        if self.pipeline._disabled:
            actions = self.pipeline.disabled_actions
        # Check here if we should disable so that we only use the disabled
        # reporters /after/ the last disable_at failure is still reported as
        # normal.
        if (self.pipeline.disable_at and not self.pipeline._disabled and
            self.pipeline._consecutive_failures >= self.pipeline.disable_at):
            self.pipeline._disabled = True
        if actions:
            try:
                self.log.info("Reporting item %s, actions: %s" %
                              (item, actions))
                ret = self.sendReport(actions, self.pipeline.source, item)
                if ret:
                    self.log.error("Reporting item %s received: %s" %
                                   (item, ret))
            except:
                self.log.exception("Exception while reporting:")
                item.setReportedResult('ERROR')
        self.updateBuildDescriptions(item.current_build_set)
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
