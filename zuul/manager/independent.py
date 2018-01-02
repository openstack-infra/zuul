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
from zuul.manager import PipelineManager, DynamicChangeQueueContextManager


class IndependentPipelineManager(PipelineManager):
    """PipelineManager that puts every Change into its own ChangeQueue."""

    changes_merge = False

    def _postConfig(self, layout):
        super(IndependentPipelineManager, self)._postConfig(layout)

    def getChangeQueue(self, change, existing=None):
        # creates a new change queue for every change
        if existing:
            return DynamicChangeQueueContextManager(existing)
        change_queue = model.ChangeQueue(self.pipeline)
        change_queue.addProject(change.project)
        self.pipeline.addQueue(change_queue)
        self.log.debug("Dynamically created queue %s", change_queue)
        return DynamicChangeQueueContextManager(change_queue)

    def enqueueChangesAhead(self, change, quiet, ignore_requirements,
                            change_queue, history=None):
        if history and change.number in history:
            # detected dependency cycle
            self.log.warn("Dependency cycle detected")
            return False
        if hasattr(change, 'number'):
            history = history or []
            history.append(change.number)
        else:
            # Don't enqueue dependencies ahead of a non-change ref.
            return True

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
                               live=False, change_queue=change_queue,
                               history=history)
            if not r:
                return False
        return True

    def checkForChangesNeededBy(self, change, change_queue):
        if self.pipeline.ignore_dependencies:
            return True
        self.log.debug("Checking for changes needed by %s:" % change)
        # Return true if okay to proceed enqueing this change,
        # false if the change should not be enqueued.
        if (hasattr(change, 'commit_needs_changes') and
            (change.refresh_deps or change.commit_needs_changes is None)):
            self.updateCommitDependencies(change, None)
        if not hasattr(change, 'needs_changes'):
            self.log.debug("  %s does not support dependencies" % type(change))
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
