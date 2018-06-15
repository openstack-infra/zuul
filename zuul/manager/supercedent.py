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


class SupercedentPipelineManager(PipelineManager):
    """PipelineManager with one queue per project and a window of 1"""

    changes_merge = False

    def getChangeQueue(self, change, existing=None):
        # creates a new change queue for every project-ref
        # combination.
        if existing:
            return DynamicChangeQueueContextManager(existing)

        # Don't use Pipeline.getQueue to find an existing queue
        # because we're matching project and ref.
        for queue in self.pipeline.queues:
            if (queue.queue[-1].change.project == change.project and
                queue.queue[-1].change.ref == change.ref):
                self.log.debug("Found existing queue %s", queue)
                return DynamicChangeQueueContextManager(queue)
        change_queue = model.ChangeQueue(
            self.pipeline,
            window=1,
            window_floor=1,
            window_increase_type='none',
            window_decrease_type='none')
        change_queue.addProject(change.project)
        self.pipeline.addQueue(change_queue)
        self.log.debug("Dynamically created queue %s", change_queue)
        return DynamicChangeQueueContextManager(change_queue)

    def _pruneQueues(self):
        # Leave the first item in the queue, as it's running, and the
        # last item, as it's the most recent, but remove any items in
        # between.  This is what causes the last item to "supercede"
        # any previously enqueued items (which we know aren't running
        # jobs because the window size is 1).
        for queue in self.pipeline.queues:
            remove = queue.queue[1:-1]
            for item in remove:
                self.log.debug("Item %s is superceded by %s, removing" %
                               (item, queue.queue[-1]))
                self.removeItem(item)

    def addChange(self, *args, **kw):
        ret = super(SupercedentPipelineManager, self).addChange(
            *args, **kw)
        if ret:
            self._pruneQueues()
        return ret

    def dequeueItem(self, item):
        super(SupercedentPipelineManager, self).dequeueItem(item)
        # A supercedent pipeline manager dynamically removes empty
        # queues
        if not item.queue.queue:
            self.pipeline.removeQueue(item.queue)
