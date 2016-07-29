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

from zuul import model
from zuul.manager import BasePipelineManager, StaticChangeQueueContextManager


class DependentPipelineManager(BasePipelineManager):
    """PipelineManager for handling interrelated Changes.

    The DependentPipelineManager puts Changes that share a Pipeline
    into a shared :py:class:`~zuul.model.ChangeQueue`. It them processes them
    using the Optmistic Branch Prediction logic with Nearest Non-Failing Item
    reparenting algorithm for handling errors.
    """
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
            change_queue = model.ChangeQueue(
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
