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

import re
import time
from uuid import uuid4
import extras

OrderedDict = extras.try_imports(['collections.OrderedDict',
                                  'ordereddict.OrderedDict'])


MERGER_MERGE = 1          # "git merge"
MERGER_MERGE_RESOLVE = 2  # "git merge -s resolve"
MERGER_CHERRY_PICK = 3    # "git cherry-pick"

MERGER_MAP = {
    'merge': MERGER_MERGE,
    'merge-resolve': MERGER_MERGE_RESOLVE,
    'cherry-pick': MERGER_CHERRY_PICK,
}

PRECEDENCE_NORMAL = 0
PRECEDENCE_LOW = 1
PRECEDENCE_HIGH = 2

PRECEDENCE_MAP = {
    None: PRECEDENCE_NORMAL,
    'low': PRECEDENCE_LOW,
    'normal': PRECEDENCE_NORMAL,
    'high': PRECEDENCE_HIGH,
}


def time_to_seconds(s):
    if s.endswith('s'):
        return int(s[:-1])
    if s.endswith('m'):
        return int(s[:-1]) * 60
    if s.endswith('h'):
        return int(s[:-1]) * 60 * 60
    if s.endswith('d'):
        return int(s[:-1]) * 24 * 60 * 60
    if s.endswith('w'):
        return int(s[:-1]) * 7 * 24 * 60 * 60
    raise Exception("Unable to parse time value: %s" % s)


def normalizeCategory(name):
    name = name.lower()
    return re.sub(' ', '-', name)


class Pipeline(object):
    """A top-level pipeline such as check, gate, post, etc."""
    def __init__(self, name):
        self.name = name
        self.description = None
        self.failure_message = None
        self.merge_failure_message = None
        self.success_message = None
        self.footer_message = None
        self.dequeue_on_new_patchset = True
        self.job_trees = {}  # project -> JobTree
        self.manager = None
        self.queues = []
        self.precedence = PRECEDENCE_NORMAL
        self.trigger = None
        self.start_actions = None
        self.success_actions = None
        self.failure_actions = None
        self.window = None
        self.window_floor = None
        self.window_increase_type = None
        self.window_increase_factor = None
        self.window_decrease_type = None
        self.window_decrease_factor = None

    def __repr__(self):
        return '<Pipeline %s>' % self.name

    def setManager(self, manager):
        self.manager = manager

    def addProject(self, project):
        job_tree = JobTree(None)  # Null job == job tree root
        self.job_trees[project] = job_tree
        return job_tree

    def getProjects(self):
        return sorted(self.job_trees.keys(), lambda a, b: cmp(a.name, b.name))

    def addQueue(self, queue):
        self.queues.append(queue)

    def getQueue(self, project):
        for queue in self.queues:
            if project in queue.projects:
                return queue
        return None

    def getJobTree(self, project):
        tree = self.job_trees.get(project)
        return tree

    def getJobs(self, changeish):
        tree = self.getJobTree(changeish.project)
        if not tree:
            return []
        return changeish.filterJobs(tree.getJobs())

    def _findJobsToRun(self, job_trees, item):
        torun = []
        if item.item_ahead:
            # Only run jobs if any 'hold' jobs on the change ahead
            # have completed successfully.
            if self.isHoldingFollowingChanges(item.item_ahead):
                return []
        for tree in job_trees:
            job = tree.job
            result = None
            if job:
                if not job.changeMatches(item.change):
                    continue
                build = item.current_build_set.getBuild(job.name)
                if build:
                    result = build.result
                else:
                    # There is no build for the root of this job tree,
                    # so we should run it.
                    torun.append(job)
            # If there is no job, this is a null job tree, and we should
            # run all of its jobs.
            if result == 'SUCCESS' or not job:
                torun.extend(self._findJobsToRun(tree.job_trees, item))
        return torun

    def findJobsToRun(self, item):
        tree = self.getJobTree(item.change.project)
        if not tree:
            return []
        return self._findJobsToRun(tree.job_trees, item)

    def haveAllJobsStarted(self, item):
        for job in self.getJobs(item.change):
            build = item.current_build_set.getBuild(job.name)
            if not build or not build.start_time:
                return False
        return True

    def areAllJobsComplete(self, item):
        for job in self.getJobs(item.change):
            build = item.current_build_set.getBuild(job.name)
            if not build or not build.result:
                return False
        return True

    def didAllJobsSucceed(self, item):
        for job in self.getJobs(item.change):
            if not job.voting:
                continue
            build = item.current_build_set.getBuild(job.name)
            if not build:
                return False
            if build.result != 'SUCCESS':
                return False
        return True

    def didMergerSucceed(self, item):
        if item.current_build_set.unable_to_merge:
            return False
        return True

    def didAnyJobFail(self, item):
        for job in self.getJobs(item.change):
            if not job.voting:
                continue
            build = item.current_build_set.getBuild(job.name)
            if build and build.result and (build.result != 'SUCCESS'):
                return True
        return False

    def isHoldingFollowingChanges(self, item):
        for job in self.getJobs(item.change):
            if not job.hold_following_changes:
                continue
            build = item.current_build_set.getBuild(job.name)
            if not build:
                return True
            if build.result != 'SUCCESS':
                return True

        if not item.item_ahead:
            return False
        return self.isHoldingFollowingChanges(item.item_ahead)

    def setResult(self, item, build):
        if build.retry:
            item.removeBuild(build)
        elif build.result != 'SUCCESS':
            # Get a JobTree from a Job so we can find only its dependent jobs
            root = self.getJobTree(item.change.project)
            tree = root.getJobTreeForJob(build.job)
            for job in tree.getJobs():
                fakebuild = Build(job, None)
                fakebuild.result = 'SKIPPED'
                item.addBuild(fakebuild)

    def setUnableToMerge(self, item):
        item.current_build_set.unable_to_merge = True
        root = self.getJobTree(item.change.project)
        for job in root.getJobs():
            fakebuild = Build(job, None)
            fakebuild.result = 'SKIPPED'
            item.addBuild(fakebuild)

    def setDequeuedNeedingChange(self, item):
        item.dequeued_needing_change = True
        root = self.getJobTree(item.change.project)
        for job in root.getJobs():
            fakebuild = Build(job, None)
            fakebuild.result = 'SKIPPED'
            item.addBuild(fakebuild)

    def getChangesInQueue(self):
        changes = []
        for shared_queue in self.queues:
            changes.extend([x.change for x in shared_queue.queue])
        return changes

    def getAllItems(self):
        items = []
        for shared_queue in self.queues:
            items.extend(shared_queue.queue)
        return items

    def formatStatusHTML(self):
        ret = ''
        for queue in self.queues:
            if len(self.queues) > 1:
                s = 'Change queue: %s' % queue.name
                ret += s + '\n'
                ret += '-' * len(s) + '\n'
            for item in queue.queue:
                ret += self.formatStatus(item, html=True)
        return ret

    def formatStatusJSON(self):
        j_pipeline = dict(name=self.name,
                          description=self.description)
        j_queues = []
        j_pipeline['change_queues'] = j_queues
        for queue in self.queues:
            j_queue = dict(name=queue.name)
            j_queues.append(j_queue)
            j_queue['heads'] = []
            j_queue['window'] = queue.window
            j_queue['dependent'] = queue.dependent

            j_changes = []
            for e in queue.queue:
                if not e.item_ahead:
                    if j_changes:
                        j_queue['heads'].append(j_changes)
                    j_changes = []
                j_changes.append(e.formatJSON())
                if (len(j_changes) > 1 and
                    (j_changes[-2]['remaining_time'] is not None) and
                    (j_changes[-1]['remaining_time'] is not None)):
                    j_changes[-1]['remaining_time'] = max(
                        j_changes[-2]['remaining_time'],
                        j_changes[-1]['remaining_time'])
            if j_changes:
                j_queue['heads'].append(j_changes)
        return j_pipeline


class ActionReporter(object):
    """An ActionReporter has a reporter and its configured paramaters"""

    def __repr__(self):
        return '<ActionReporter %s, %s>' % (self.reporter, self.params)

    def __init__(self, reporter, params):
        self.reporter = reporter
        self.params = params

    def report(self, change, message):
        """Sends the built message off to the configured reporter.
        Takes the change and message and adds the configured parameters.
        """
        return self.reporter.report(change, message, self.params)

    def getSubmitAllowNeeds(self):
        """Gets the submit allow needs from the reporter based off the
        parameters."""
        return self.reporter.getSubmitAllowNeeds(self.params)


class ChangeQueue(object):
    """DependentPipelines have multiple parallel queues shared by
    different projects; this is one of them.  For instance, there may
    a queue shared by interrelated projects foo and bar, and a second
    queue for independent project baz.  Pipelines have one or more
    PipelineQueues."""
    def __init__(self, pipeline, dependent=True, window=0, window_floor=1,
                 window_increase_type='linear', window_increase_factor=1,
                 window_decrease_type='exponential', window_decrease_factor=2):
        self.pipeline = pipeline
        self.name = ''
        self.assigned_name = None
        self.generated_name = None
        self.projects = []
        self._jobs = set()
        self.queue = []
        self.dependent = dependent
        self.window = window
        self.window_floor = window_floor
        self.window_increase_type = window_increase_type
        self.window_increase_factor = window_increase_factor
        self.window_decrease_type = window_decrease_type
        self.window_decrease_factor = window_decrease_factor

    def __repr__(self):
        return '<ChangeQueue %s: %s>' % (self.pipeline.name, self.name)

    def getJobs(self):
        return self._jobs

    def addProject(self, project):
        if project not in self.projects:
            self.projects.append(project)
            self._jobs |= set(self.pipeline.getJobTree(project).getJobs())

            names = [x.name for x in self.projects]
            names.sort()
            self.generated_name = ', '.join(names)

            for job in self._jobs:
                if job.queue_name:
                    if (self.assigned_name and
                        job.queue_name != self.assigned_name):
                        raise Exception("More than one name assigned to "
                                        "change queue: %s != %s" %
                                        (self.assigned_name, job.queue_name))
                    self.assigned_name = job.queue_name
            self.name = self.assigned_name or self.generated_name

    def enqueueChange(self, change):
        item = QueueItem(self.pipeline, change)
        self.enqueueItem(item)
        item.enqueue_time = time.time()
        return item

    def enqueueItem(self, item):
        item.pipeline = self.pipeline
        if self.dependent and self.queue:
            item.item_ahead = self.queue[-1]
            item.item_ahead.items_behind.append(item)
        self.queue.append(item)

    def dequeueItem(self, item):
        if item in self.queue:
            self.queue.remove(item)
        if item.item_ahead:
            item.item_ahead.items_behind.remove(item)
        for item_behind in item.items_behind:
            if item.item_ahead:
                item.item_ahead.items_behind.append(item_behind)
            item_behind.item_ahead = item.item_ahead
        item.item_ahead = None
        item.items_behind = []
        item.dequeue_time = time.time()

    def moveItem(self, item, item_ahead):
        if not self.dependent:
            return False
        if item.item_ahead == item_ahead:
            return False
        # Remove from current location
        if item.item_ahead:
            item.item_ahead.items_behind.remove(item)
        for item_behind in item.items_behind:
            if item.item_ahead:
                item.item_ahead.items_behind.append(item_behind)
            item_behind.item_ahead = item.item_ahead
        # Add to new location
        item.item_ahead = item_ahead
        item.items_behind = []
        if item.item_ahead:
            item.item_ahead.items_behind.append(item)
        return True

    def mergeChangeQueue(self, other):
        for project in other.projects:
            self.addProject(project)
        self.window = min(self.window, other.window)
        # TODO merge semantics

    def isActionable(self, item):
        if self.dependent and self.window:
            return item in self.queue[:self.window]
        else:
            return True

    def increaseWindowSize(self):
        if self.dependent:
            if self.window_increase_type == 'linear':
                self.window += self.window_increase_factor
            elif self.window_increase_type == 'exponential':
                self.window *= self.window_increase_factor

    def decreaseWindowSize(self):
        if self.dependent:
            if self.window_decrease_type == 'linear':
                self.window = max(
                    self.window_floor,
                    self.window - self.window_decrease_factor)
            elif self.window_decrease_type == 'exponential':
                self.window = max(
                    self.window_floor,
                    self.window / self.window_decrease_factor)


class Project(object):
    def __init__(self, name):
        self.name = name
        self.merge_mode = MERGER_MERGE_RESOLVE

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Project %s>' % (self.name)


class Job(object):
    def __init__(self, name):
        # If you add attributes here, be sure to add them to the copy method.
        self.name = name
        self.queue_name = None
        self.failure_message = None
        self.success_message = None
        self.failure_pattern = None
        self.success_pattern = None
        self.parameter_function = None
        self.hold_following_changes = False
        self.voting = True
        self.branches = []
        self._branches = []
        self.files = []
        self._files = []
        self.swift = {}

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s>' % (self.name)

    def copy(self, other):
        if other.failure_message:
            self.failure_message = other.failure_message
        if other.success_message:
            self.success_message = other.success_message
        if other.failure_pattern:
            self.failure_pattern = other.failure_pattern
        if other.success_pattern:
            self.success_pattern = other.success_pattern
        if other.parameter_function:
            self.parameter_function = other.parameter_function
        if other.branches:
            self.branches = other.branches[:]
            self._branches = other._branches[:]
        if other.files:
            self.files = other.files[:]
            self._files = other._files[:]
        if other.swift:
            self.swift.update(other.swift)
        self.hold_following_changes = other.hold_following_changes
        self.voting = other.voting

    def changeMatches(self, change):
        matches_branch = False
        for branch in self.branches:
            if hasattr(change, 'branch') and branch.match(change.branch):
                matches_branch = True
            if hasattr(change, 'ref') and branch.match(change.ref):
                matches_branch = True
        if self.branches and not matches_branch:
            return False

        matches_file = False
        for f in self.files:
            if hasattr(change, 'files'):
                for cf in change.files:
                    if f.match(cf):
                        matches_file = True
        if self.files and not matches_file:
            return False

        return True


class JobTree(object):
    """ A JobTree represents an instance of one Job, and holds JobTrees
    whose jobs should be run if that Job succeeds.  A root node of a
    JobTree will have no associated Job. """

    def __init__(self, job):
        self.job = job
        self.job_trees = []

    def addJob(self, job):
        if job not in [x.job for x in self.job_trees]:
            t = JobTree(job)
            self.job_trees.append(t)
            return t

    def getJobs(self):
        jobs = []
        for x in self.job_trees:
            jobs.append(x.job)
            jobs.extend(x.getJobs())
        return jobs

    def getJobTreeForJob(self, job):
        if self.job == job:
            return self
        for tree in self.job_trees:
            ret = tree.getJobTreeForJob(job)
            if ret:
                return ret
        return None


class Build(object):
    def __init__(self, job, uuid):
        self.job = job
        self.uuid = uuid
        self.url = None
        self.number = None
        self.result = None
        self.build_set = None
        self.launch_time = time.time()
        self.start_time = None
        self.end_time = None
        self.estimated_time = None
        self.pipeline = None
        self.canceled = False
        self.retry = False
        self.parameters = {}
        self.worker = Worker()

    def __repr__(self):
        return ('<Build %s of %s on %s>' %
                (self.uuid, self.job.name, self.worker))


class Worker(object):
    """A model of the worker running a job"""
    def __init__(self):
        self.name = "Unknown"
        self.hostname = None
        self.ips = []
        self.fqdn = None
        self.program = None
        self.version = None
        self.extra = {}

    def updateFromData(self, data):
        """Update worker information if contained in the WORK_DATA response."""
        self.name = data.get('worker_name', self.name)
        self.hostname = data.get('worker_hostname', self.hostname)
        self.ips = data.get('worker_ips', self.ips)
        self.fqdn = data.get('worker_fqdn', self.fqdn)
        self.program = data.get('worker_program', self.program)
        self.version = data.get('worker_version', self.version)
        self.extra = data.get('worker_extra', self.extra)

    def __repr__(self):
        return '<Worker %s>' % self.name


class BuildSet(object):
    # Merge states:
    NEW = 1
    PENDING = 2
    COMPLETE = 3

    def __init__(self, item):
        self.item = item
        self.other_changes = []
        self.builds = {}
        self.result = None
        self.next_build_set = None
        self.previous_build_set = None
        self.ref = None
        self.commit = None
        self.zuul_url = None
        self.unable_to_merge = False
        self.failing_reasons = []
        self.merge_state = self.NEW

    def setConfiguration(self):
        # The change isn't enqueued until after it's created
        # so we don't know what the other changes ahead will be
        # until jobs start.
        if not self.other_changes:
            next_item = self.item.item_ahead
            while next_item:
                self.other_changes.append(next_item.change)
                next_item = next_item.item_ahead
        if not self.ref:
            self.ref = 'Z' + uuid4().hex

    def addBuild(self, build):
        self.builds[build.job.name] = build
        build.build_set = self

    def removeBuild(self, build):
        del self.builds[build.job.name]

    def getBuild(self, job_name):
        return self.builds.get(job_name)

    def getBuilds(self):
        keys = self.builds.keys()
        keys.sort()
        return [self.builds.get(x) for x in keys]


class QueueItem(object):
    """A changish inside of a Pipeline queue"""

    def __init__(self, pipeline, change):
        self.pipeline = pipeline
        self.change = change  # a changeish
        self.build_sets = []
        self.dequeued_needing_change = False
        self.current_build_set = BuildSet(self)
        self.build_sets.append(self.current_build_set)
        self.item_ahead = None
        self.items_behind = []
        self.enqueue_time = None
        self.dequeue_time = None
        self.reported = False
        self.active = False

    def __repr__(self):
        if self.pipeline:
            pipeline = self.pipeline.name
        else:
            pipeline = None
        return '<QueueItem 0x%x for %s in %s>' % (
            id(self), self.change, pipeline)

    def resetAllBuilds(self):
        old = self.current_build_set
        self.current_build_set.result = 'CANCELED'
        self.current_build_set = BuildSet(self)
        old.next_build_set = self.current_build_set
        self.current_build_set.previous_build_set = old
        self.build_sets.append(self.current_build_set)

    def addBuild(self, build):
        self.current_build_set.addBuild(build)
        build.pipeline = self.pipeline

    def removeBuild(self, build):
        self.current_build_set.removeBuild(build)

    def setReportedResult(self, result):
        self.current_build_set.result = result

    def formatJSON(self):
        changeish = self.change
        ret = {}
        ret['active'] = self.active
        if hasattr(changeish, 'url') and changeish.url is not None:
            ret['url'] = changeish.url
        else:
            ret['url'] = None
        ret['id'] = changeish._id()
        if self.item_ahead:
            ret['item_ahead'] = self.item_ahead.change._id()
        else:
            ret['item_ahead'] = None
        ret['items_behind'] = [i.change._id() for i in self.items_behind]
        ret['failing_reasons'] = self.current_build_set.failing_reasons
        ret['zuul_ref'] = self.current_build_set.ref
        ret['project'] = changeish.project.name
        ret['enqueue_time'] = int(self.enqueue_time * 1000)
        ret['jobs'] = []
        max_remaining = 0
        for job in self.pipeline.getJobs(changeish):
            now = time.time()
            build = self.current_build_set.getBuild(job.name)
            elapsed = None
            remaining = None
            result = None
            url = None
            worker = None
            if build:
                result = build.result
                url = build.url
                if build.start_time:
                    if build.end_time:
                        elapsed = int((build.end_time -
                                       build.start_time) * 1000)
                        remaining = 0
                    else:
                        elapsed = int((now - build.start_time) * 1000)
                        if build.estimated_time:
                            remaining = max(
                                int(build.estimated_time * 1000) - elapsed,
                                0)
                worker = {
                    'name': build.worker.name,
                    'hostname': build.worker.hostname,
                    'ips': build.worker.ips,
                    'fqdn': build.worker.fqdn,
                    'program': build.worker.program,
                    'version': build.worker.version,
                    'extra': build.worker.extra
                }
            if remaining and remaining > max_remaining:
                max_remaining = remaining

            ret['jobs'].append({
                'name': job.name,
                'elapsed_time': elapsed,
                'remaining_time': remaining,
                'url': url,
                'result': result,
                'voting': job.voting,
                'uuid': build.uuid if build else None,
                'launch_time': build.launch_time if build else None,
                'start_time': build.start_time if build else None,
                'end_time': build.end_time if build else None,
                'estimated_time': build.estimated_time if build else None,
                'pipeline': build.pipeline.name if build else None,
                'canceled': build.canceled if build else None,
                'retry': build.retry if build else None,
                'number': build.number if build else None,
                'parameters': build.parameters if build else None,
                'worker': worker
            })

        if self.pipeline.haveAllJobsStarted(self):
            ret['remaining_time'] = max_remaining
        else:
            ret['remaining_time'] = None
        return ret

    def formatStatus(self, indent=0, html=False):
        changeish = self.change
        indent_str = ' ' * indent
        ret = ''
        if html and hasattr(changeish, 'url') and changeish.url is not None:
            ret += '%sProject %s change <a href="%s">%s</a>\n' % (
                indent_str,
                changeish.project.name,
                changeish.url,
                changeish._id())
        else:
            ret += '%sProject %s change %s based on %s\n' % (
                indent_str,
                changeish.project.name,
                changeish._id(),
                self.item_ahead)
        for job in self.pipeline.getJobs(changeish):
            build = self.current_build_set.getBuild(job.name)
            if build:
                result = build.result
            else:
                result = None
            job_name = job.name
            if not job.voting:
                voting = ' (non-voting)'
            else:
                voting = ''
            if html:
                if build:
                    url = build.url
                else:
                    url = None
                if url is not None:
                    job_name = '<a href="%s">%s</a>' % (url, job_name)
            ret += '%s  %s: %s%s' % (indent_str, job_name, result, voting)
            ret += '\n'
        return ret


class Changeish(object):
    """Something like a change; either a change or a ref"""

    def __init__(self, project):
        self.project = project

    def getBasePath(self):
        base_path = ''
        if hasattr(self, 'refspec'):
            base_path = "%s/%s/%s" % (
                self.number[-2:], self.number, self.patchset)
        elif hasattr(self, 'ref'):
            base_path = "%s/%s" % (self.newrev[:2], self.newrev)

        return base_path

    def equals(self, other):
        raise NotImplementedError()

    def isUpdateOf(self, other):
        raise NotImplementedError()

    def filterJobs(self, jobs):
        return filter(lambda job: job.changeMatches(self), jobs)

    def getRelatedChanges(self):
        return set()


class Change(Changeish):
    def __init__(self, project):
        super(Change, self).__init__(project)
        self.branch = None
        self.number = None
        self.url = None
        self.patchset = None
        self.refspec = None

        self.files = []
        self.needs_change = None
        self.needed_by_changes = []
        self.is_current_patchset = True
        self.can_merge = False
        self.is_merged = False
        self.failed_to_merge = False
        self.approvals = []
        self.open = None
        self.status = None

    def _id(self):
        return '%s,%s' % (self.number, self.patchset)

    def __repr__(self):
        return '<Change 0x%x %s>' % (id(self), self._id())

    def equals(self, other):
        if self.number == other.number and self.patchset == other.patchset:
            return True
        return False

    def isUpdateOf(self, other):
        if ((hasattr(other, 'number') and self.number == other.number) and
            (hasattr(other, 'patchset') and
             self.patchset is not None and
             other.patchset is not None and
             int(self.patchset) > int(other.patchset))):
            return True
        return False

    def getRelatedChanges(self):
        related = set()
        if self.needs_change:
            related.add(self.needs_change)
        for c in self.needed_by_changes:
            related.add(c)
            related.update(c.getRelatedChanges())
        return related


class Ref(Changeish):
    def __init__(self, project):
        super(Ref, self).__init__(project)
        self.ref = None
        self.oldrev = None
        self.newrev = None

    def _id(self):
        return self.newrev

    def __repr__(self):
        rep = None
        if self.newrev == '0000000000000000000000000000000000000000':
            rep = '<Ref 0x%x deletes %s from %s' % (
                  id(self), self.ref, self.oldrev)
        elif self.oldrev == '0000000000000000000000000000000000000000':
            rep = '<Ref 0x%x creates %s on %s>' % (
                  id(self), self.ref, self.newrev)
        else:
            # Catch all
            rep = '<Ref 0x%x %s updated %s..%s>' % (
                  id(self), self.ref, self.oldrev, self.newrev)

        return rep

    def equals(self, other):
        if (self.project == other.project
            and self.ref == other.ref
            and self.newrev == other.newrev):
            return True
        return False

    def isUpdateOf(self, other):
        return False


class NullChange(Changeish):
    def __repr__(self):
        return '<NullChange for %s>' % (self.project)

    def _id(self):
        return None

    def equals(self, other):
        if (self.project == other.project):
            return True
        return False

    def isUpdateOf(self, other):
        return False


class TriggerEvent(object):
    def __init__(self):
        self.data = None
        # common
        self.type = None
        self.project_name = None
        self.trigger_name = None
        # Representation of the user account that performed the event.
        self.account = None
        # patchset-created, comment-added, etc.
        self.change_number = None
        self.change_url = None
        self.patch_number = None
        self.refspec = None
        self.approvals = []
        self.branch = None
        self.comment = None
        # ref-updated
        self.ref = None
        self.oldrev = None
        self.newrev = None
        # timer
        self.timespec = None
        # For events that arrive with a destination pipeline (eg, from
        # an admin command, etc):
        self.forced_pipeline = None

    def __repr__(self):
        ret = '<TriggerEvent %s %s' % (self.type, self.project_name)

        if self.branch:
            ret += " %s" % self.branch
        if self.change_number:
            ret += " %s,%s" % (self.change_number, self.patch_number)
        if self.approvals:
            ret += ' ' + ', '.join(
                ['%s:%s' % (a['type'], a['value']) for a in self.approvals])
        ret += '>'

        return ret

    def getChange(self, project, trigger):
        if self.change_number:
            change = trigger.getChange(self.change_number, self.patch_number)
        elif self.ref:
            change = Ref(project)
            change.ref = self.ref
            change.oldrev = self.oldrev
            change.newrev = self.newrev
            change.url = trigger.getGitwebUrl(project, sha=self.newrev)
        else:
            change = NullChange(project)

        return change


class EventFilter(object):
    def __init__(self, types=[], branches=[], refs=[], event_approvals={},
                 comment_filters=[], email_filters=[], username_filters=[],
                 timespecs=[], require_approvals=[]):
        self._types = types
        self._branches = branches
        self._refs = refs
        self._comment_filters = comment_filters
        self._email_filters = email_filters
        self._username_filters = username_filters
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comment_filters = [re.compile(x) for x in comment_filters]
        self.email_filters = [re.compile(x) for x in email_filters]
        self.username_filters = [re.compile(x) for x in username_filters]
        self.event_approvals = event_approvals
        self.require_approvals = require_approvals
        self.timespecs = timespecs

        for a in self.require_approvals:
            if 'older-than' in a:
                a['older-than'] = time_to_seconds(a['older-than'])
            if 'newer-than' in a:
                a['newer-than'] = time_to_seconds(a['newer-than'])
            if 'email-filter' in a:
                a['email-filter'] = re.compile(a['email-filter'])

    def __repr__(self):
        ret = '<EventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.event_approvals:
            ret += ' event_approvals: %s' % ', '.join(
                ['%s:%s' % a for a in self.event_approvals.items()])
        if self._comment_filters:
            ret += ' comment_filters: %s' % ', '.join(self._comment_filters)
        if self._email_filters:
            ret += ' email_filters: %s' % ', '.join(self._email_filters)
        if self._username_filters:
            ret += ' username_filters: %s' % ', '.join(self._username_filters)
        if self.timespecs:
            ret += ' timespecs: %s' % ', '.join(self.timespecs)
        ret += '>'

        return ret

    def matches(self, event, change):
        # event types are ORed
        matches_type = False
        for etype in self.types:
            if etype.match(event.type):
                matches_type = True
        if self.types and not matches_type:
            return False

        # branches are ORed
        matches_branch = False
        for branch in self.branches:
            if branch.match(event.branch):
                matches_branch = True
        if self.branches and not matches_branch:
            return False

        # refs are ORed
        matches_ref = False
        for ref in self.refs:
            if ref.match(event.ref):
                matches_ref = True
        if self.refs and not matches_ref:
            return False

        # comment_filters are ORed
        matches_comment_filter = False
        for comment_filter in self.comment_filters:
            if (event.comment is not None and
                comment_filter.search(event.comment)):
                matches_comment_filter = True
        if self.comment_filters and not matches_comment_filter:
            return False

        # We better have an account provided by Gerrit to do
        # email filtering.
        if event.account is not None:
            account_email = event.account.get('email')
            # email_filters are ORed
            matches_email_filter = False
            for email_filter in self.email_filters:
                if (account_email is not None and
                    email_filter.search(account_email)):
                    matches_email_filter = True
            if self.email_filters and not matches_email_filter:
                return False

            # username_filters are ORed
            account_username = event.account.get('username')
            matches_username_filter = False
            for username_filter in self.username_filters:
                if (account_username is not None and
                    username_filter.search(account_username)):
                    matches_username_filter = True
            if self.username_filters and not matches_username_filter:
                return False

        # approvals are ANDed
        for category, value in self.event_approvals.items():
            matches_approval = False
            for eapproval in event.approvals:
                if (normalizeCategory(eapproval['description']) == category and
                    int(eapproval['value']) == int(value)):
                    matches_approval = True
            if not matches_approval:
                return False

        if self.require_approvals and not change.approvals:
            # A change with no approvals can not match
            return False

        now = time.time()
        for rapproval in self.require_approvals:
            matches_approval = False
            for approval in change.approvals:
                if 'description' not in approval:
                    continue
                found_approval = True
                by = approval.get('by', {})
                for k, v in rapproval.items():
                    if k == 'username':
                        if (by.get('username', '') != v):
                            found_approval = False
                    elif k == 'email-filter':
                        if (not v.search(by.get('email', ''))):
                            found_approval = False
                    elif k == 'newer-than':
                        t = now - v
                        if (approval['grantedOn'] < t):
                            found_approval = False
                    elif k == 'older-than':
                        t = now - v
                        if (approval['grantedOn'] >= t):
                            found_approval = False
                    else:
                        if (normalizeCategory(approval['description']) != k or
                            int(approval['value']) != v):
                            found_approval = False
                if found_approval:
                    matches_approval = True
                    break
            if not matches_approval:
                return False

        # timespecs are ORed
        matches_timespec = False
        for timespec in self.timespecs:
            if (event.timespec == timespec):
                matches_timespec = True
        if self.timespecs and not matches_timespec:
            return False

        return True


class ChangeishFilter(object):
    def __init__(self, open=None, statuses=[], approvals=[]):
        self.open = open
        self.statuses = statuses
        self.approvals = approvals

        for a in self.approvals:
            if 'older-than' in a:
                a['older-than'] = time_to_seconds(a['older-than'])
            if 'newer-than' in a:
                a['newer-than'] = time_to_seconds(a['newer-than'])
            if 'email-filter' in a:
                a['email-filter'] = re.compile(a['email-filter'])

    def __repr__(self):
        ret = '<ChangeishFilter'

        if self.open is not None:
            ret += ' open: %s' % self.open
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.approvals:
            ret += ' approvals: %s' % ', '.join(str(self.approvals))
        ret += '>'

        return ret

    def matches(self, change):
        if self.open is not None:
            if self.open != change.open:
                return False

        if self.statuses:
            if change.status not in self.statuses:
                return False

        if self.approvals and not change.approvals:
            # A change with no approvals can not match
            return False

        now = time.time()
        for rapproval in self.approvals:
            matches_approval = False
            for approval in change.approvals:
                if 'description' not in approval:
                    continue
                found_approval = True
                by = approval.get('by', {})
                for k, v in rapproval.items():
                    if k == 'username':
                        if (by.get('username', '') != v):
                            found_approval = False
                    elif k == 'email-filter':
                        if (not v.search(by.get('email', ''))):
                            found_approval = False
                    elif k == 'newer-than':
                        t = now - v
                        if (approval['grantedOn'] < t):
                            found_approval = False
                    elif k == 'older-than':
                        t = now - v
                        if (approval['grantedOn'] >= t):
                            found_approval = False
                    else:
                        if (normalizeCategory(approval['description']) != k or
                            int(approval['value']) != v):
                            found_approval = False
                if found_approval:
                    matches_approval = True
                    break
            if not matches_approval:
                return False

        return True


class Layout(object):
    def __init__(self):
        self.projects = {}
        self.pipelines = OrderedDict()
        self.jobs = {}
        self.metajobs = []

    def getJob(self, name):
        if name in self.jobs:
            return self.jobs[name]
        job = Job(name)
        if name.startswith('^'):
            # This is a meta-job
            regex = re.compile(name)
            self.metajobs.append((regex, job))
        else:
            # Apply attributes from matching meta-jobs
            for regex, metajob in self.metajobs:
                if regex.match(name):
                    job.copy(metajob)
            self.jobs[name] = job
        return job
