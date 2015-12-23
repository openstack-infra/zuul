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
import re
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
    def __init__(self, name, layout):
        self.name = name
        self.layout = layout
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
        self.triggers = []
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

    @property
    def actions(self):
        return (
            self.start_actions +
            self.success_actions +
            self.failure_actions +
            self.merge_failure_actions +
            self.disabled_actions
        )

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

    def _findJobsToRun(self, job_trees, item):
        torun = []
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
        if not item.live:
            return []
        tree = item.job_tree
        if not tree:
            return []
        return self._findJobsToRun(tree.job_trees, item)

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
            tree = item.job_tree.getJobTreeForJob(build.job)
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

            names = [x.name for x in self.projects]
            names.sort()
            self.generated_name = ', '.join(names)
            self.name = self.assigned_name or self.generated_name

    def enqueueChange(self, change):
        item = QueueItem(self, change)
        item.freezeJobTree()
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
                    self.window / self.window_decrease_factor)


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


class Inheritable(object):
    def __init__(self, parent=None):
        self.parent = parent

    def __getattribute__(self, name):
        parent = object.__getattribute__(self, 'parent')
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            if parent:
                return getattr(parent, name)
            raise


class Job(object):
    attributes = dict(
        timeout=None,
        # variables={},
        # nodes=[],
        # auth={},
        workspace=None,
        pre_run=None,
        post_run=None,
        voting=None,
        failure_message=None,
        success_message=None,
        failure_url=None,
        success_url=None,
        # Matchers.  These are separate so they can be individually
        # overidden.
        branch_matcher=None,
        file_matcher=None,
        irrelevant_file_matcher=None,  # skip-if
        swift=None,  # TODOv3(jeblair): move to auth
        parameter_function=None,  # TODOv3(jeblair): remove
        success_pattern=None,  # TODOv3(jeblair): remove
    )

    def __init__(self, name):
        self.name = name
        for k, v in self.attributes.items():
            setattr(self, k, v)

    def __equals__(self, other):
        # Compare the name and all inheritable attributes to determine
        # whether two jobs with the same name are identically
        # configured.  Useful upon reconfiguration.
        if not isinstance(other, Job):
            return False
        if self.name != other.name:
            return False
        for k, v in self.attributes.items():
            if getattr(self, k) != getattr(other, k):
                return False
        return True

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s>' % (self.name,)

    def inheritFrom(self, other):
        """Copy the inheritable attributes which have been set on the other
        job to this job."""

        if not isinstance(other, Job):
            raise Exception("Job unable to inherit from %s" % (other,))
        for k, v in self.attributes.items():
            if getattr(other, k) != v:
                setattr(self, k, getattr(other, k))

    def changeMatches(self, change):
        if self.branch_matcher and not self.branch_matcher.matches(change):
            return False

        if self.file_matcher and not self.file_matcher.matches(change):
            return False

        # NB: This is a negative match.
        if (self.irrelevant_file_matcher and
            self.irrelevant_file_matcher.matches(change)):
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

    def inheritFrom(self, other):
        if other.job:
            self.job = Job(other.job.name)
            self.job.inheritFrom(other.job)
        for other_tree in other.job_trees:
            this_tree = self.getJobTreeForJob(other_tree.job)
            if not this_tree:
                this_tree = JobTree(None)
                self.job_trees.append(this_tree)
            this_tree.inheritFrom(other_tree)


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
        self.job_tree = None

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

    def _createJobTree(self, job_trees, parent):
        for tree in job_trees:
            job = tree.job
            if not job.changeMatches(self.change):
                continue
            frozen_job = Job(job.name)
            frozen_tree = JobTree(frozen_job)
            inherited = set()
            for variant in self.pipeline.layout.getJobs(job.name):
                if variant.changeMatches(self.change):
                    if variant not in inherited:
                        frozen_job.inheritFrom(variant)
                        inherited.add(variant)
            if job not in inherited:
                # Only update from the job in the tree if it is
                # unique, otherwise we might unset an attribute we
                # have overloaded.
                frozen_job.inheritFrom(job)
            parent.job_trees.append(frozen_tree)
            self._createJobTree(tree.job_trees, frozen_tree)

    def createJobTree(self):
        project_tree = self.pipeline.getJobTree(self.change.project)
        ret = JobTree(None)
        self._createJobTree(project_tree.job_trees, ret)
        return ret

    def freezeJobTree(self):
        """Find or create actual matching jobs for this item's change and
        store the resulting job tree."""
        self.job_tree = self.createJobTree()

    def getJobs(self):
        if not self.live or not self.job_tree:
            return []
        return self.job_tree.getJobs()

    def formatJSON(self):
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

        # Internal mechanism to track if the change needs a refresh from cache
        self._needs_refresh = False

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
                    pass
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
                if (by.get('username', '') != v):
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


class ProjectPipelineConfig(object):
    # Represents a project cofiguration in the context of a pipeline
    def __init__(self):
        self.job_tree = None
        self.queue_name = None
        # TODOv3(jeblair): add merge mode


class ProjectConfig(object):
    # Represents a project cofiguration
    def __init__(self, name):
        self.name = name
        self.pipelines = {}


class UnparsedAbideConfig(object):
    # A collection of yaml lists that has not yet been parsed into
    # objects.
    def __init__(self):
        self.tenants = []

    def extend(self, conf):
        if isinstance(conf, UnparsedAbideConfig):
            self.tenants.extend(conf.tenants)
            return

        if not isinstance(conf, list):
            raise Exception("Configuration items must be in the form of "
                            "a list of dictionaries (when parsing %s)" %
                            (conf,))
        for item in conf:
            if not isinstance(item, dict):
                raise Exception("Configuration items must be in the form of "
                                "a list of dictionaries (when parsing %s)" %
                                (conf,))
            if len(item.keys()) > 1:
                raise Exception("Configuration item dictionaries must have "
                                "a single key (when parsing %s)" %
                                (conf,))
            key, value = item.items()[0]
            if key == 'tenant':
                self.tenants.append(value)
            else:
                raise Exception("Configuration item not recognized "
                                "(when parsing %s)" %
                                (conf,))


class UnparsedTenantConfig(object):
    # A collection of yaml lists that has not yet been parsed into
    # objects.
    def __init__(self):
        self.pipelines = []
        self.jobs = []
        self.project_templates = []
        self.projects = []

    def extend(self, conf):
        if isinstance(conf, UnparsedTenantConfig):
            self.pipelines.extend(conf.pipelines)
            self.jobs.extend(conf.jobs)
            self.project_templates.extend(conf.project_templates)
            self.projects.extend(conf.projects)
            return

        if not isinstance(conf, list):
            raise Exception("Configuration items must be in the form of "
                            "a list of dictionaries (when parsing %s)" %
                            (conf,))
        for item in conf:
            if not isinstance(item, dict):
                raise Exception("Configuration items must be in the form of "
                                "a list of dictionaries (when parsing %s)" %
                                (conf,))
            if len(item.keys()) > 1:
                raise Exception("Configuration item dictionaries must have "
                                "a single key (when parsing %s)" %
                                (conf,))
            key, value = item.items()[0]
            if key == 'project':
                self.projects.append(value)
            elif key == 'job':
                self.jobs.append(value)
            elif key == 'project-template':
                self.project_templates.append(value)
            elif key == 'pipeline':
                self.pipelines.append(value)
            else:
                raise Exception("Configuration item not recognized "
                                "(when parsing %s)" %
                                (conf,))


class Layout(object):
    def __init__(self):
        self.projects = {}
        self.project_configs = {}
        self.project_templates = {}
        self.pipelines = OrderedDict()
        # This is a dictionary of name -> [jobs].  The first element
        # of the list is the first job added with that name.  It is
        # the reference definition for a given job.  Subsequent
        # elements are aspects of that job with different matchers
        # that override some attribute of the job.  These aspects all
        # inherit from the reference definition.
        self.jobs = {}

    def getJob(self, name):
        if name in self.jobs:
            return self.jobs[name][0]
        raise Exception("Job %s not defined" % (name,))

    def getJobs(self, name):
        return self.jobs.get(name, [])

    def addJob(self, job):
        if job.name in self.jobs:
            self.jobs[job.name].append(job)
        else:
            self.jobs[job.name] = [job]

    def addPipeline(self, pipeline):
        self.pipelines[pipeline.name] = pipeline

    def addProjectTemplate(self, project_template):
        self.project_templates[project_template.name] = project_template

    def addProjectConfig(self, project_config):
        self.project_configs[project_config.name] = project_config
        # TODOv3(jeblair): tidy up the relationship between pipelines
        # and projects and projectconfigs
        for pipeline_name, pipeline_config in project_config.pipelines.items():
            pipeline = self.pipelines[pipeline_name]
            project = pipeline.source.getProject(project_config.name)
            pipeline.job_trees[project] = pipeline_config.job_tree


class Tenant(object):
    def __init__(self, name):
        self.name = name
        self.layout = None


class Abide(object):
    def __init__(self):
        self.tenants = OrderedDict()
