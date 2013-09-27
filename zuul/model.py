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


class Pipeline(object):
    """A top-level pipeline such as check, gate, post, etc."""
    def __init__(self, name):
        self.name = name
        self.description = None
        self.failure_message = None
        self.success_message = None
        self.dequeue_on_new_patchset = True
        self.job_trees = {}  # project -> JobTree
        self.manager = None
        self.queues = []
        self.precedence = PRECEDENCE_NORMAL
        self.trigger = None
        self.start_actions = None
        self.success_actions = None
        self.failure_actions = None

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

    def setUnableToMerge(self, item, msg):
        item.current_build_set.unable_to_merge = True
        item.current_build_set.unable_to_merge_message = msg
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

            j_changes = []
            for e in queue.queue:
                if not e.item_ahead:
                    if j_changes:
                        j_queue['heads'].append(j_changes)
                    j_changes = []
                j_changes.append(self.formatItemJSON(e))
                if (len(j_changes) > 1 and
                    (j_changes[-2]['remaining_time'] is not None) and
                    (j_changes[-1]['remaining_time'] is not None)):
                    j_changes[-1]['remaining_time'] = max(
                        j_changes[-2]['remaining_time'],
                        j_changes[-1]['remaining_time'])
            if j_changes:
                j_queue['heads'].append(j_changes)
        return j_pipeline

    def formatStatus(self, item, indent=0, html=False):
        changeish = item.change
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
                item.item_ahead)
        for job in self.getJobs(changeish):
            build = item.current_build_set.getBuild(job.name)
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

    def formatItemJSON(self, item):
        changeish = item.change
        ret = {}
        if hasattr(changeish, 'url') and changeish.url is not None:
            ret['url'] = changeish.url
        else:
            ret['url'] = None
        ret['id'] = changeish._id()
        if item.item_ahead:
            ret['item_ahead'] = item.item_ahead.change._id()
        else:
            ret['item_ahead'] = None
        ret['items_behind'] = [i.change._id() for i in item.items_behind]
        ret['failing_reasons'] = item.current_build_set.failing_reasons
        ret['zuul_ref'] = item.current_build_set.ref
        ret['project'] = changeish.project.name
        ret['enqueue_time'] = int(item.enqueue_time * 1000)
        ret['jobs'] = []
        max_remaining = 0
        for job in self.getJobs(changeish):
            now = time.time()
            build = item.current_build_set.getBuild(job.name)
            elapsed = None
            remaining = None
            result = None
            url = None
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
            if remaining and remaining > max_remaining:
                max_remaining = remaining
            ret['jobs'].append(
                dict(
                    name=job.name,
                    elapsed_time=elapsed,
                    remaining_time=remaining,
                    url=url,
                    result=result,
                    voting=job.voting))
        if self.haveAllJobsStarted(item):
            ret['remaining_time'] = max_remaining
        else:
            ret['remaining_time'] = None
        return ret


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
    def __init__(self, pipeline, dependent=True):
        self.pipeline = pipeline
        self.name = ''
        self.projects = []
        self._jobs = set()
        self.queue = []
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
        item = QueueItem(self.pipeline, change)
        self.enqueueItem(item)
        item.enqueue_time = time.time()
        return item

    def enqueueItem(self, item):
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

    def __repr__(self):
        return '<Build %s of %s>' % (self.uuid, self.job.name)


class BuildSet(object):
    def __init__(self, item):
        self.item = item
        self.other_changes = []
        self.builds = {}
        self.result = None
        self.next_build_set = None
        self.previous_build_set = None
        self.ref = None
        self.commit = None
        self.unable_to_merge = False
        self.unable_to_merge_message = None
        self.failing_reasons = []

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


class Changeish(object):
    """Something like a change; either a change or a ref"""
    is_reportable = False

    def __init__(self, project):
        self.project = project

    def equals(self, other):
        raise NotImplementedError()

    def isUpdateOf(self, other):
        raise NotImplementedError()

    def filterJobs(self, jobs):
        return filter(lambda job: job.changeMatches(self), jobs)

    def getRelatedChanges(self):
        return set()


class Change(Changeish):
    is_reportable = True

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
    is_reportable = False

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
    is_reportable = False

    def _id(self):
        return None

    def equals(self, other):
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
    def __init__(self, types=[], branches=[], refs=[], approvals={},
                 comment_filters=[], email_filters=[], timespecs=[]):
        self._types = types
        self._branches = branches
        self._refs = refs
        self._comment_filters = comment_filters
        self._email_filters = email_filters
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comment_filters = [re.compile(x) for x in comment_filters]
        self.email_filters = [re.compile(x) for x in email_filters]
        self.approvals = approvals
        self.timespecs = timespecs

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
        if self._comment_filters:
            ret += ' comment_filters: %s' % ', '.join(self._comment_filters)
        if self._email_filters:
            ret += ' email_filters: %s' % ', '.join(self._email_filters)
        if self.timespecs:
            ret += ' timespecs: %s' % ', '.join(self.timespecs)
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

        # approvals are ANDed
        for category, value in self.approvals.items():
            matches_approval = False
            for eapproval in event.approvals:
                if (normalizeCategory(eapproval['description']) == category and
                    int(eapproval['value']) == int(value)):
                    matches_approval = True
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
