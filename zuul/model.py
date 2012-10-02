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


FAST_FORWARD_ONLY = 1
MERGE_ALWAYS = 2
MERGE_IF_NECESSARY = 3
CHERRY_PICK = 4


class Pipeline(object):
    """A top-level pipeline such as check, gate, post, etc."""
    def __init__(self, name):
        self.name = name
        self.job_trees = {}  # project -> JobTree
        self.manager = None
        self.queues = []

    def __repr__(self):
        return '<Pipeline %s>' % self.name

    def setManager(self, manager):
        self.manager = manager

    def addProject(self, project):
        job_tree = JobTree(None)  # Null job == job tree root
        self.job_trees[project] = job_tree
        return job_tree

    def getProjects(self):
        return self.job_trees.keys()

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

    def _findJobsToRun(self, job_trees, changeish):
        torun = []
        if changeish.change_ahead:
            # Only run jobs if any 'hold' jobs on the change ahead
            # have completed successfully.
            if self.isHoldingFollowingChanges(changeish.change_ahead):
                return []
        for tree in job_trees:
            job = tree.job
            result = None
            if job:
                if not job.changeMatches(changeish):
                    continue
                build = changeish.current_build_set.getBuild(job.name)
                if build:
                    result = build.result
                else:
                    # There is no build for the root of this job tree,
                    # so we should run it.
                    torun.append(job)
            # If there is no job, this is a null job tree, and we should
            # run all of its jobs.
            if result == 'SUCCESS' or not job:
                torun.extend(self._findJobsToRun(tree.job_trees, changeish))
        return torun

    def findJobsToRun(self, changeish):
        tree = self.getJobTree(changeish.project)
        if not tree:
            return []
        return self._findJobsToRun(tree.job_trees, changeish)

    def areAllJobsComplete(self, changeish):
        for job in self.getJobs(changeish):
            build = changeish.current_build_set.getBuild(job.name)
            if not build or not build.result:
                return False
        return True

    def didAllJobsSucceed(self, changeish):
        for job in self.getJobs(changeish):
            if not job.voting:
                continue
            build = changeish.current_build_set.getBuild(job.name)
            if not build:
                return False
            if build.result != 'SUCCESS':
                return False
        return True

    def didAnyJobFail(self, changeish):
        for job in self.getJobs(changeish):
            if not job.voting:
                continue
            build = changeish.current_build_set.getBuild(job.name)
            if build and build.result == 'FAILURE':
                return True
        return False

    def isHoldingFollowingChanges(self, changeish):
        for job in self.getJobs(changeish):
            if not job.hold_following_changes:
                continue
            build = changeish.current_build_set.getBuild(job.name)
            if not build:
                return True
            if build.result != 'SUCCESS':
                return True
        if not changeish.change_ahead:
            return False
        return self.isHoldingFollowingChanges(changeish.change_ahead)

    def setResult(self, changeish, build):
        if build.result != 'SUCCESS':
            # Get a JobTree from a Job so we can find only its dependent jobs
            root = self.getJobTree(changeish.project)
            tree = root.getJobTreeForJob(build.job)
            for job in tree.getJobs():
                fakebuild = Build(job, None)
                fakebuild.result = 'SKIPPED'
                changeish.addBuild(fakebuild)

    def setUnableToMerge(self, changeish):
        changeish.current_build_set.unable_to_merge = True
        root = self.getJobTree(changeish.project)
        for job in root.getJobs():
            fakebuild = Build(job, None)
            fakebuild.result = 'SKIPPED'
            changeish.addBuild(fakebuild)

    def setDequeuedNeedingChange(self, changeish):
        changeish.dequeued_needing_change = True
        root = self.getJobTree(changeish.project)
        for job in root.getJobs():
            fakebuild = Build(job, None)
            fakebuild.result = 'SKIPPED'
            changeish.addBuild(fakebuild)

    def getChangesInQueue(self):
        changes = []
        for shared_queue in self.queues:
            changes.extend(shared_queue.queue)
        return changes

    def getAllChanges(self):
        changes = []
        for shared_queue in self.queues:
            changes.extend(shared_queue.queue)
            changes.extend(shared_queue.severed_heads)
        return changes

    def formatStatusHTML(self):
        ret = ''
        for queue in self.queues:
            if len(self.queues) > 1:
                s = 'Change queue: %s' % queue.name
                ret += s + '\n'
                ret += '-' * len(s) + '\n'
            for head in queue.getHeads():
                ret += self.formatStatus(head, html=True)
        return ret

    def formatStatus(self, changeish, indent=0, html=False):
        indent_str = ' ' * indent
        ret = ''
        if html and hasattr(changeish, 'url') and changeish.url is not None:
            ret += '%sProject %s change <a href="%s">%s</a>\n' % (
                indent_str,
                changeish.project.name,
                changeish.url,
                changeish._id())
        else:
            ret += '%sProject %s change %s\n' % (indent_str,
                                                 changeish.project.name,
                                                 changeish._id())
        for job in self.getJobs(changeish):
            build = changeish.current_build_set.getBuild(job.name)
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
        if changeish.change_behind:
            ret += '%sFollowed by:\n' % (indent_str)
            ret += self.formatStatus(changeish.change_behind, indent + 2, html)
        return ret


class ChangeQueue(object):
    """DependentPipelines have multiple parallel queues shared by
    different projects; this is one of them.  For instance, there may
    a queue shared by interrelated projects foo and bar, and a second
    queue for independent project baz.  Pipelines have one or more
    PipelineQueues."""
    def __init__(self, pipeline, dependent=True):
        self.pipeline = pipeline
        self.name = ''
        self.projects = []
        self._jobs = set()
        self.queue = []
        self.severed_heads = []
        self.dependent = dependent

    def __repr__(self):
        return '<ChangeQueue %s: %s>' % (self.pipeline.name, self.name)

    def getJobs(self):
        return self._jobs

    def addProject(self, project):
        if project not in self.projects:
            self.projects.append(project)
            names = [x.name for x in self.projects]
            names.sort()
            self.name = ', '.join(names)
            self._jobs |= set(self.pipeline.getJobTree(project).getJobs())

    def enqueueChange(self, change):
        if self.dependent and self.queue:
            change.change_ahead = self.queue[-1]
            change.change_ahead.change_behind = change
        self.queue.append(change)

    def dequeueChange(self, change):
        if change in self.queue:
            self.queue.remove(change)
        if change in self.severed_heads:
            self.severed_heads.remove(change)
        if change.change_ahead:
            change.change_ahead.change_behind = change.change_behind
        if change.change_behind:
            change.change_behind.change_ahead = change.change_ahead
        change.change_ahead = None
        change.change_behind = None

    def addSeveredHead(self, change):
        self.severed_heads.append(change)

    def mergeChangeQueue(self, other):
        for project in other.projects:
            self.addProject(project)

    def getHead(self):
        if not self.queue:
            return None
        return self.queue[0]

    def getHeads(self):
        heads = []
        if self.dependent:
            h = self.getHead()
            if h:
                heads.append(h)
        else:
            heads.extend(self.queue)
        heads.extend(self.severed_heads)
        return heads


class Project(object):
    def __init__(self, name):
        self.name = name
        self.merge_mode = MERGE_IF_NECESSARY

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Project %s>' % (self.name)


class Job(object):
    def __init__(self, name):
        # If you add attributes here, be sure to add them to the copy method.
        self.name = name
        self.failure_message = None
        self.success_message = None
        self.parameter_function = None
        self.hold_following_changes = False
        self.voting = True
        self.branches = []
        self._branches = []

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s>' % (self.name)

    def copy(self, other):
        self.failure_message = other.failure_message
        self.success_message = other.success_message
        self.parameter_function = other.parameter_function
        self.hold_following_changes = other.hold_following_changes
        self.voting = other.voting
        self.branches = other.branches[:]
        self._branches = other._branches[:]

    def changeMatches(self, change):
        if not self.branches:
            return True
        for branch in self.branches:
            if hasattr(change, 'branch') and branch.match(change.branch):
                return True
            if hasattr(change, 'ref') and branch.match(change.ref):
                return True
        return False


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
        self.base_url = None
        self.url = None
        self.number = None
        self.result = None
        self.build_set = None
        self.launch_time = time.time()

    def __repr__(self):
        return '<Build %s of %s>' % (self.uuid, self.job.name)


class BuildSet(object):
    def __init__(self, change):
        self.change = change
        self.other_changes = []
        self.builds = {}
        self.result = None
        self.next_build_set = None
        self.previous_build_set = None
        self.ref = None
        self.commit = None
        self.unable_to_merge = False

    def setConfiguration(self):
        # The change isn't enqueued until after it's created
        # so we don't know what the other changes ahead will be
        # until jobs start.
        if not self.other_changes:
            next_change = self.change.change_ahead
            while next_change:
                self.other_changes.append(next_change)
                next_change = next_change.change_ahead
        if not self.ref:
            self.ref = 'Z' + uuid4().hex

    def addBuild(self, build):
        self.builds[build.job.name] = build
        build.build_set = self

    def getBuild(self, job_name):
        return self.builds.get(job_name)

    def getBuilds(self):
        keys = self.builds.keys()
        keys.sort()
        return [self.builds.get(x) for x in keys]


class Changeish(object):
    """Something like a change; either a change or a ref"""
    is_reportable = False

    def __init__(self, project):
        self.project = project
        self.build_sets = []
        self.dequeued_needing_change = False
        self.current_build_set = BuildSet(self)
        self.build_sets.append(self.current_build_set)
        self.change_ahead = None
        self.change_behind = None

    def equals(self, other):
        raise NotImplementedError()

    def filterJobs(self, jobs):
        return filter(lambda job: job.changeMatches(self), jobs)

    def resetAllBuilds(self):
        old = self.current_build_set
        self.current_build_set.result = 'CANCELED'
        self.current_build_set = BuildSet(self)
        old.next_build_set = self.current_build_set
        self.current_build_set.previous_build_set = old
        self.build_sets.append(self.current_build_set)

    def addBuild(self, build):
        self.current_build_set.addBuild(build)


class Change(Changeish):
    is_reportable = True

    def __init__(self, project):
        super(Change, self).__init__(project)
        self.branch = None
        self.number = None
        self.url = None
        self.patchset = None
        self.refspec = None

        self.reported = False
        self.needs_change = None
        self.needed_by_changes = []
        self.is_current_patchset = True
        self.can_merge = False
        self.is_merged = False

    def _id(self):
        return '%s,%s' % (self.number, self.patchset)

    def __repr__(self):
        return '<Change 0x%x %s>' % (id(self), self._id())

    def equals(self, other):
        if self.number == other.number and self.patchset == other.patchset:
            return True
        return False

    def setReportedResult(self, result):
        self.current_build_set.result = result


class Ref(Changeish):
    is_reportable = False

    def __init__(self, project):
        super(Ref, self).__init__(project)
        self.ref = None
        self.oldrev = None
        self.newrev = None

    def _id(self):
        return self.newrev

    def equals(self, other):
        if (self.project == other.project
            and self.ref == other.ref
            and self.newrev == other.newrev):
            return True
        return False


class TriggerEvent(object):
    def __init__(self):
        self.data = None
        # common
        self.type = None
        self.project_name = None
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
        # TODO: make the scheduler deal with events (which may have
        # changes) rather than changes so that we don't have to create
        # "fake" changes for events that aren't associated with changes.

        if self.change_number:
            change = trigger.getChange(self.change_number, self.patch_number)
        if self.ref:
            change = Ref(project)
            change.ref = self.ref
            change.oldrev = self.oldrev
            change.newrev = self.newrev

        return change


class EventFilter(object):
    def __init__(self, types=[], branches=[], refs=[], approvals={},
                 comment_filters=[]):
        self._types = types
        self._branches = branches
        self._refs = refs
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comment_filters = [re.compile(x) for x in comment_filters]
        self.approvals = approvals

    def __repr__(self):
        ret = '<EventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.approvals:
            ret += ' approvals: %s' % ', '.join(
                ['%s:%s' % a for a in self.approvals.items()])
        ret += '>'

        return ret

    def matches(self, event):
        def normalizeCategory(name):
            name = name.lower()
            return re.sub(' ', '-', name)

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

        # approvals are ANDed
        for category, value in self.approvals.items():
            matches_approval = False
            for eapproval in event.approvals:
                if (normalizeCategory(eapproval['description']) == category and
                    int(eapproval['value']) == int(value)):
                    matches_approval = True
            if not matches_approval:
                return False
        return True
