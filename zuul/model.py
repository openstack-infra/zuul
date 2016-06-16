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

import copy
import os
import re
import struct
import time
from uuid import uuid4
import extras

OrderedDict = extras.try_imports(['collections.OrderedDict',
                                  'ordereddict.OrderedDict'])


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes

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
        self.ignore_dependencies = False
        self.job_trees = {}  # project -> JobTree
        self.manager = None
        self.queues = []
        self.precedence = PRECEDENCE_NORMAL
        self.source = None
        self.start_actions = []
        self.success_actions = []
        self.failure_actions = []
        self.merge_failure_actions = []
        self.disabled_actions = []
        self.disable_at = None
        self._consecutive_failures = 0
        self._disabled = False
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
        # cmp is not in python3, applied idiom from
        # http://python-future.org/compatible_idioms.html#cmp
        return sorted(
            self.job_trees.keys(),
            key=lambda p: p.name)

    def addQueue(self, queue):
        self.queues.append(queue)

    def getQueue(self, project):
        for queue in self.queues:
            if project in queue.projects:
                return queue
        return None

    def removeQueue(self, queue):
        self.queues.remove(queue)

    def getJobTree(self, project):
        tree = self.job_trees.get(project)
        return tree

    def getJobs(self, item):
        if not item.live:
            return []
        tree = self.getJobTree(item.change.project)
        if not tree:
            return []
        return item.change.filterJobs(tree.getJobs())

    def _findJobsToRun(self, job_trees, item, mutex):
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
                    if mutex.acquire(item, job):
                        # If this job needs a mutex, either acquire it or make
                        # sure that we have it before running the job.
                        torun.append(job)
            # If there is no job, this is a null job tree, and we should
            # run all of its jobs.
            if result == 'SUCCESS' or not job:
                torun.extend(self._findJobsToRun(tree.job_trees, item, mutex))
        return torun

    def findJobsToRun(self, item, mutex):
        if not item.live:
            return []
        tree = self.getJobTree(item.change.project)
        if not tree:
            return []
        return self._findJobsToRun(tree.job_trees, item, mutex)

    def haveAllJobsStarted(self, item):
        for job in self.getJobs(item):
            build = item.current_build_set.getBuild(job.name)
            if not build or not build.start_time:
                return False
        return True

    def areAllJobsComplete(self, item):
        for job in self.getJobs(item):
            build = item.current_build_set.getBuild(job.name)
            if not build or not build.result:
                return False
        return True

    def didAllJobsSucceed(self, item):
        for job in self.getJobs(item):
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
        for job in self.getJobs(item):
            if not job.voting:
                continue
            build = item.current_build_set.getBuild(job.name)
            if build and build.result and (build.result != 'SUCCESS'):
                return True
        return False

    def isHoldingFollowingChanges(self, item):
        if not item.live:
            return False
        for job in self.getJobs(item):
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

    def formatStatusJSON(self, url_pattern=None):
        j_pipeline = dict(name=self.name,
                          description=self.description)
        j_queues = []
        j_pipeline['change_queues'] = j_queues
        for queue in self.queues:
            j_queue = dict(name=queue.name)
            j_queues.append(j_queue)
            j_queue['heads'] = []
            j_queue['window'] = queue.window

            j_changes = []
            for e in queue.queue:
                if not e.item_ahead:
                    if j_changes:
                        j_queue['heads'].append(j_changes)
                    j_changes = []
                j_changes.append(e.formatJSON(url_pattern))
                if (len(j_changes) > 1 and
                        (j_changes[-2]['remaining_time'] is not None) and
                        (j_changes[-1]['remaining_time'] is not None)):
                    j_changes[-1]['remaining_time'] = max(
                        j_changes[-2]['remaining_time'],
                        j_changes[-1]['remaining_time'])
            if j_changes:
                j_queue['heads'].append(j_changes)
        return j_pipeline


class ChangeQueue(object):
    """DependentPipelines have multiple parallel queues shared by
    different projects; this is one of them.  For instance, there may
    a queue shared by interrelated projects foo and bar, and a second
    queue for independent project baz.  Pipelines have one or more
    ChangeQueues."""
    def __init__(self, pipeline, window=0, window_floor=1,
                 window_increase_type='linear', window_increase_factor=1,
                 window_decrease_type='exponential', window_decrease_factor=2):
        self.pipeline = pipeline
        self.name = ''
        self.assigned_name = None
        self.generated_name = None
        self.projects = []
        self._jobs = set()
        self.queue = []
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
        item = QueueItem(self, change)
        self.enqueueItem(item)
        item.enqueue_time = time.time()
        return item

    def enqueueItem(self, item):
        item.pipeline = self.pipeline
        item.queue = self
        if self.queue:
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
        if self.window:
            return item in self.queue[:self.window]
        else:
            return True

    def increaseWindowSize(self):
        if self.window:
            if self.window_increase_type == 'linear':
                self.window += self.window_increase_factor
            elif self.window_increase_type == 'exponential':
                self.window *= self.window_increase_factor

    def decreaseWindowSize(self):
        if self.window:
            if self.window_decrease_type == 'linear':
                self.window = max(
                    self.window_floor,
                    self.window - self.window_decrease_factor)
            elif self.window_decrease_type == 'exponential':
                self.window = max(
                    self.window_floor,
                    int(self.window / self.window_decrease_factor))


class Project(object):
    def __init__(self, name, foreign=False):
        self.name = name
        self.merge_mode = MERGER_MERGE_RESOLVE
        # foreign projects are those referenced in dependencies
        # of layout projects, this should matter
        # when deciding whether to enqueue their changes
        self.foreign = foreign

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
        self.tags = set()
        self.mutex = None
        # A metajob should only supply values for attributes that have
        # been explicitly provided, so avoid setting boolean defaults.
        if self.is_metajob:
            self.hold_following_changes = None
            self.voting = None
        else:
            self.hold_following_changes = False
            self.voting = True
        self.branches = []
        self._branches = []
        self.files = []
        self._files = []
        self.skip_if_matcher = None
        self.swift = {}

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s>' % (self.name)

    @property
    def is_metajob(self):
        return self.name.startswith('^')

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
        if other.skip_if_matcher:
            self.skip_if_matcher = other.skip_if_matcher.copy()
        if other.swift:
            self.swift.update(other.swift)
        if other.mutex:
            self.mutex = other.mutex
        # Tags are merged via a union rather than a destructive copy
        # because they are intended to accumulate as metajobs are
        # applied.
        if other.tags:
            self.tags = self.tags.union(other.tags)
        # Only non-None values should be copied for boolean attributes.
        if other.hold_following_changes is not None:
            self.hold_following_changes = other.hold_following_changes
        if other.voting is not None:
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

        if self.skip_if_matcher and self.skip_if_matcher.matches(change):
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
        for tree in self.job_trees:
            if tree.job == job:
                return tree

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
        self.node_labels = []
        self.node_name = None

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

    states_map = {
        1: 'NEW',
        2: 'PENDING',
        3: 'COMPLETE',
    }

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

    def __repr__(self):
        return '<BuildSet item: %s #builds: %s merge state: %s>' % (
            self.item,
            len(self.builds),
            self.getStateName(self.merge_state))

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

    def getStateName(self, state_num):
        return self.states_map.get(
            state_num, 'UNKNOWN (%s)' % state_num)

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

    def __init__(self, queue, change):
        self.pipeline = queue.pipeline
        self.queue = queue
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
        self.active = False  # Whether an item is within an active window
        self.live = True  # Whether an item is intended to be processed at all

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

    def formatJobResult(self, job, url_pattern=None):
        build = self.current_build_set.getBuild(job.name)
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
        url = None
        if pattern:
            try:
                url = pattern.format(change=self.change,
                                     pipeline=self.pipeline,
                                     job=job,
                                     build=build)
            except Exception:
                pass  # FIXME: log this or something?
        if not url:
            url = build.url or job.name
        return (result, url)

    def formatJSON(self, url_pattern=None):
        changeish = self.change
        ret = {}
        ret['active'] = self.active
        ret['live'] = self.live
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
        if changeish.project:
            ret['project'] = changeish.project.name
        else:
            # For cross-project dependencies with the depends-on
            # project not known to zuul, the project is None
            # Set it to a static value
            ret['project'] = "Unknown Project"
        ret['enqueue_time'] = int(self.enqueue_time * 1000)
        ret['jobs'] = []
        if hasattr(changeish, 'owner'):
            ret['owner'] = changeish.owner
        else:
            ret['owner'] = None
        max_remaining = 0
        for job in self.pipeline.getJobs(self):
            now = time.time()
            build = self.current_build_set.getBuild(job.name)
            elapsed = None
            remaining = None
            result = None
            build_url = None
            report_url = None
            worker = None
            if build:
                result = build.result
                build_url = build.url
                (unused, report_url) = self.formatJobResult(job, url_pattern)
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
                'url': build_url,
                'report_url': report_url,
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
                'node_labels': build.node_labels if build else [],
                'node_name': build.node_name if build else None,
                'worker': worker,
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
        for job in self.pipeline.getJobs(self):
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
        self.needs_changes = []
        self.needed_by_changes = []
        self.is_current_patchset = True
        self.can_merge = False
        self.is_merged = False
        self.failed_to_merge = False
        self.approvals = []
        self.open = None
        self.status = None
        self.owner = None

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
        for c in self.needs_changes:
            related.add(c)
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
        if (self.project == other.project
            and other._id() is None):
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
        # zuultrigger
        self.pipeline_name = None
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


class BaseFilter(object):
    def __init__(self, required_approvals=[], reject_approvals=[]):
        self._required_approvals = copy.deepcopy(required_approvals)
        self.required_approvals = self._tidy_approvals(required_approvals)
        self._reject_approvals = copy.deepcopy(reject_approvals)
        self.reject_approvals = self._tidy_approvals(reject_approvals)

    def _tidy_approvals(self, approvals):
        for a in approvals:
            for k, v in a.items():
                if k == 'username':
                    a['username'] = re.compile(v)
                elif k in ['email', 'email-filter']:
                    a['email'] = re.compile(v)
                elif k == 'newer-than':
                    a[k] = time_to_seconds(v)
                elif k == 'older-than':
                    a[k] = time_to_seconds(v)
            if 'email-filter' in a:
                del a['email-filter']
        return approvals

    def _match_approval_required_approval(self, rapproval, approval):
        # Check if the required approval and approval match
        if 'description' not in approval:
            return False
        now = time.time()
        by = approval.get('by', {})
        for k, v in rapproval.items():
            if k == 'username':
                if (not v.search(by.get('username', ''))):
                        return False
            elif k == 'email':
                if (not v.search(by.get('email', ''))):
                        return False
            elif k == 'newer-than':
                t = now - v
                if (approval['grantedOn'] < t):
                        return False
            elif k == 'older-than':
                t = now - v
                if (approval['grantedOn'] >= t):
                    return False
            else:
                if not isinstance(v, list):
                    v = [v]
                if (normalizeCategory(approval['description']) != k or
                        int(approval['value']) not in v):
                    return False
        return True

    def matchesApprovals(self, change):
        if (self.required_approvals and not change.approvals
                or self.reject_approvals and not change.approvals):
            # A change with no approvals can not match
            return False

        # TODO(jhesketh): If we wanted to optimise this slightly we could
        # analyse both the REQUIRE and REJECT filters by looping over the
        # approvals on the change and keeping track of what we have checked
        # rather than needing to loop on the change approvals twice
        return (self.matchesRequiredApprovals(change) and
                self.matchesNoRejectApprovals(change))

    def matchesRequiredApprovals(self, change):
        # Check if any approvals match the requirements
        for rapproval in self.required_approvals:
            matches_rapproval = False
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # We have a matching approval so this requirement is
                    # fulfilled
                    matches_rapproval = True
                    break
            if not matches_rapproval:
                return False
        return True

    def matchesNoRejectApprovals(self, change):
        # Check to make sure no approvals match a reject criteria
        for rapproval in self.reject_approvals:
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # A reject approval has been matched, so we reject
                    # immediately
                    return False
        # To get here no rejects can have been matched so we should be good to
        # queue
        return True


class EventFilter(BaseFilter):
    def __init__(self, trigger, types=[], branches=[], refs=[],
                 event_approvals={}, comments=[], emails=[], usernames=[],
                 timespecs=[], required_approvals=[], reject_approvals=[],
                 pipelines=[], ignore_deletes=True):
        super(EventFilter, self).__init__(
            required_approvals=required_approvals,
            reject_approvals=reject_approvals)
        self.trigger = trigger
        self._types = types
        self._branches = branches
        self._refs = refs
        self._comments = comments
        self._emails = emails
        self._usernames = usernames
        self._pipelines = pipelines
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comments = [re.compile(x) for x in comments]
        self.emails = [re.compile(x) for x in emails]
        self.usernames = [re.compile(x) for x in usernames]
        self.pipelines = [re.compile(x) for x in pipelines]
        self.event_approvals = event_approvals
        self.timespecs = timespecs
        self.ignore_deletes = ignore_deletes

    def __repr__(self):
        ret = '<EventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._pipelines:
            ret += ' pipelines: %s' % ', '.join(self._pipelines)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.ignore_deletes:
            ret += ' ignore_deletes: %s' % self.ignore_deletes
        if self.event_approvals:
            ret += ' event_approvals: %s' % ', '.join(
                ['%s:%s' % a for a in self.event_approvals.items()])
        if self.required_approvals:
            ret += ' required_approvals: %s' % ', '.join(
                ['%s' % a for a in self._required_approvals])
        if self.reject_approvals:
            ret += ' reject_approvals: %s' % ', '.join(
                ['%s' % a for a in self._reject_approvals])
        if self._comments:
            ret += ' comments: %s' % ', '.join(self._comments)
        if self._emails:
            ret += ' emails: %s' % ', '.join(self._emails)
        if self._usernames:
            ret += ' username_filters: %s' % ', '.join(self._usernames)
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

        # pipelines are ORed
        matches_pipeline = False
        for epipe in self.pipelines:
            if epipe.match(event.pipeline_name):
                matches_pipeline = True
        if self.pipelines and not matches_pipeline:
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
        if event.ref is not None:
            for ref in self.refs:
                if ref.match(event.ref):
                    matches_ref = True
        if self.refs and not matches_ref:
            return False
        if self.ignore_deletes and event.newrev == EMPTY_GIT_REF:
            # If the updated ref has an empty git sha (all 0s),
            # then the ref is being deleted
            return False

        # comments are ORed
        matches_comment_re = False
        for comment_re in self.comments:
            if (event.comment is not None and
                comment_re.search(event.comment)):
                matches_comment_re = True
        if self.comments and not matches_comment_re:
            return False

        # We better have an account provided by Gerrit to do
        # email filtering.
        if event.account is not None:
            account_email = event.account.get('email')
            # emails are ORed
            matches_email_re = False
            for email_re in self.emails:
                if (account_email is not None and
                        email_re.search(account_email)):
                    matches_email_re = True
            if self.emails and not matches_email_re:
                return False

            # usernames are ORed
            account_username = event.account.get('username')
            matches_username_re = False
            for username_re in self.usernames:
                if (account_username is not None and
                    username_re.search(account_username)):
                    matches_username_re = True
            if self.usernames and not matches_username_re:
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

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
            return False

        # timespecs are ORed
        matches_timespec = False
        for timespec in self.timespecs:
            if (event.timespec == timespec):
                matches_timespec = True
        if self.timespecs and not matches_timespec:
            return False

        return True


class ChangeishFilter(BaseFilter):
    def __init__(self, open=None, current_patchset=None,
                 statuses=[], required_approvals=[],
                 reject_approvals=[]):
        super(ChangeishFilter, self).__init__(
            required_approvals=required_approvals,
            reject_approvals=reject_approvals)
        self.open = open
        self.current_patchset = current_patchset
        self.statuses = statuses

    def __repr__(self):
        ret = '<ChangeishFilter'

        if self.open is not None:
            ret += ' open: %s' % self.open
        if self.current_patchset is not None:
            ret += ' current-patchset: %s' % self.current_patchset
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.required_approvals:
            ret += (' required_approvals: %s' %
                    str(self.required_approvals))
        if self.reject_approvals:
            ret += (' reject_approvals: %s' %
                    str(self.reject_approvals))
        ret += '>'

        return ret

    def matches(self, change):
        if self.open is not None:
            if self.open != change.open:
                return False

        if self.current_patchset is not None:
            if self.current_patchset != change.is_current_patchset:
                return False

        if self.statuses:
            if change.status not in self.statuses:
                return False

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
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
        if job.is_metajob:
            regex = re.compile(name)
            self.metajobs.append((regex, job))
        else:
            # Apply attributes from matching meta-jobs
            for regex, metajob in self.metajobs:
                if regex.match(name):
                    job.copy(metajob)
            self.jobs[name] = job
        return job


class JobTimeData(object):
    format = 'B10H10H10B'
    version = 0

    def __init__(self, path):
        self.path = path
        self.success_times = [0 for x in range(10)]
        self.failure_times = [0 for x in range(10)]
        self.results = [0 for x in range(10)]

    def load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            data = struct.unpack(self.format, f.read())
        version = data[0]
        if version != self.version:
            raise Exception("Unkown data version")
        self.success_times = list(data[1:11])
        self.failure_times = list(data[11:21])
        self.results = list(data[21:32])

    def save(self):
        tmpfile = self.path + '.tmp'
        data = [self.version]
        data.extend(self.success_times)
        data.extend(self.failure_times)
        data.extend(self.results)
        data = struct.pack(self.format, *data)
        with open(tmpfile, 'w') as f:
            f.write(data)
        os.rename(tmpfile, self.path)

    def add(self, elapsed, result):
        elapsed = int(elapsed)
        if result == 'SUCCESS':
            self.success_times.append(elapsed)
            self.success_times.pop(0)
            result = 0
        else:
            self.failure_times.append(elapsed)
            self.failure_times.pop(0)
            result = 1
        self.results.append(result)
        self.results.pop(0)

    def getEstimatedTime(self):
        times = [x for x in self.success_times if x]
        if times:
            return float(sum(times)) / len(times)
        return 0.0


class TimeDataBase(object):
    def __init__(self, root):
        self.root = root
        self.jobs = {}

    def _getTD(self, name):
        td = self.jobs.get(name)
        if not td:
            td = JobTimeData(os.path.join(self.root, name))
            self.jobs[name] = td
            td.load()
        return td

    def getEstimatedTime(self, name):
        return self._getTD(name).getEstimatedTime()

    def update(self, name, elapsed, result):
        td = self._getTD(name)
        td.add(elapsed, result)
        td.save()
