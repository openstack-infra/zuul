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

from zuul import model
from zuul.manager import PipelineManager, StaticChangeQueueContextManager
from zuul.manager import DynamicChangeQueueContextManager


class DependentPipelineManager(PipelineManager):
    """PipelineManager for handling interrelated Changes.

    The DependentPipelineManager puts Changes that share a Pipeline
    into a shared :py:class:`~zuul.model.ChangeQueue`. It then processes them
    using the Optimistic Branch Prediction logic with Nearest Non-Failing Item
    reparenting algorithm for handling errors.
    """
    changes_merge = True

    def __init__(self, *args, **kwargs):
        super(DependentPipelineManager, self).__init__(*args, **kwargs)

    def buildChangeQueues(self, layout):
        self.log.debug("Building shared change queues")
        change_queues = {}
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
            if queue_name and queue_name in change_queues:
                change_queue = change_queues[queue_name]
            else:
                p = self.pipeline
                change_queue = model.ChangeQueue(
                    p,
                    window=p.window,
                    window_floor=p.window_floor,
                    window_increase_type=p.window_increase_type,
                    window_increase_factor=p.window_increase_factor,
                    window_decrease_type=p.window_decrease_type,
                    window_decrease_factor=p.window_decrease_factor,
                    name=queue_name)
                if queue_name:
                    # If this is a named queue, keep track of it in
                    # case it is referenced again.  Otherwise, it will
                    # have a name automatically generated from its
                    # constituent projects.
                    change_queues[queue_name] = change_queue
                self.pipeline.addQueue(change_queue)
                self.log.debug("Created queue: %s" % change_queue)
            change_queue.addProject(project)
            self.log.debug("Added project %s to queue: %s" %
                           (project, change_queue))

    def getChangeQueue(self, change, existing=None):
        if existing:
            return StaticChangeQueueContextManager(existing)
        queue = self.pipeline.getQueue(change.project)
        if queue:
            return StaticChangeQueueContextManager(queue)
        else:
            # There is no existing queue for this change. Create a
            # dynamic one for this one change's use
            change_queue = model.ChangeQueue(self.pipeline, dynamic=True)
            change_queue.addProject(change.project)
            self.pipeline.addQueue(change_queue)
            self.log.debug("Dynamically created queue %s", change_queue)
            return DynamicChangeQueueContextManager(change_queue)

    def getNodePriority(self, item):
        with self.getChangeQueue(item.change) as change_queue:
            items = change_queue.queue
            return items.index(item)

    def isChangeReadyToBeEnqueued(self, change):
        source = change.project.source
        if not source.canMerge(change, self.getSubmitAllowNeeds()):
            self.log.debug("Change %s can not merge, ignoring" % change)
            return False
        return True

    def enqueueChangesBehind(self, change, quiet, ignore_requirements,
                             change_queue):
        self.log.debug("Checking for changes needing %s:" % change)
        if not hasattr(change, 'needed_by_changes'):
            self.log.debug("  %s does not support dependencies" % type(change))
            return

        # for project in change_queue, project.source get changes, then dedup.
        sources = set()
        for project in change_queue.projects:
            sources.add(project.source)

        seen = set(change.needed_by_changes)
        needed_by_changes = change.needed_by_changes[:]
        for source in sources:
            self.log.debug("  Checking source: %s", source)
            for c in source.getChangesDependingOn(change,
                                                  change_queue.projects,
                                                  self.pipeline.tenant):
                if c not in seen:
                    seen.add(c)
                    needed_by_changes.append(c)

        self.log.debug("  Following changes: %s", needed_by_changes)

        to_enqueue = []
        for other_change in needed_by_changes:
            with self.getChangeQueue(other_change) as other_change_queue:
                if other_change_queue != change_queue:
                    self.log.debug("  Change %s in project %s can not be "
                                   "enqueued in the target queue %s" %
                                   (other_change, other_change.project,
                                    change_queue))
                    continue
            source = other_change.project.source
            if source.canMerge(other_change, self.getSubmitAllowNeeds()):
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
                            change_queue, history=None):
        if history and change in history:
            # detected dependency cycle
            self.log.warn("Dependency cycle detected")
            return False
        if hasattr(change, 'number'):
            history = history or []
            history = history + [change]
        else:
            # Don't enqueue dependencies ahead of a non-change ref.
            return True

        ret = self.checkForChangesNeededBy(change, change_queue)
        if ret in [True, False]:
            return ret
        self.log.debug("  Changes %s must be merged ahead of %s" %
                       (ret, change))
        for needed_change in ret:
            r = self.addChange(needed_change, quiet=quiet,
                               ignore_requirements=ignore_requirements,
                               change_queue=change_queue, history=history)
            if not r:
                return False
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        # Return true if okay to proceed enqueing this change,
        # false if the change should not be enqueued.
        self.log.debug("Checking for changes needed by %s:" % change)
        if (hasattr(change, 'commit_needs_changes') and
            (change.refresh_deps or change.commit_needs_changes is None)):
            self.updateCommitDependencies(change, change_queue)
        if not hasattr(change, 'needs_changes'):
            self.log.debug("  %s does not support dependencies" % type(change))
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
                if needed_change.project.source.canMerge(
                        needed_change, self.getSubmitAllowNeeds()):
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

    def dequeueItem(self, item):
        super(DependentPipelineManager, self).dequeueItem(item)
        # If this was a dynamic queue from a speculative change,
        # remove the queue (if empty)
        if item.queue.dynamic:
            if not item.queue.queue:
                self.pipeline.removeQueue(item.queue)
