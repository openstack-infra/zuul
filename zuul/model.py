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


class ChangeQueue(object):
    def __init__(self, queue_name):
        self.name = ''
        self.queue_name = queue_name
        self.projects = []
        self._jobs = set()
        self.queue = []

    def __repr__(self):
        return '<ChangeQueue %s: %s>' % (self.queue_name, self.name)

    def getJobs(self):
        return self._jobs

    def addProject(self, project):
        if project not in self.projects:
            self.projects.append(project)
            names = [x.name for x in self.projects]
            names.sort()
            self.name = ', '.join(names)
            self._jobs |= set(project.getJobs(self.queue_name))

    def enqueueChange(self, change):
        if self.queue:
            self.queue[-1].change_behind = change
            change.change_ahead = self.queue[-1]
        self.queue.append(change)
        change.queue = self

    def dequeueChange(self, change):
        if change in self.queue:
            self.queue.remove(change)

    def mergeChangeQueue(self, other):
        for project in other.projects:
            self.addProject(project)


class Job(object):
    def __init__(self, name):
        self.name = name
        self.failure_message = None
        self.success_message = None
        self.event_filters = []

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s>' % (self.name)

    def copy(self, other):
        self.failure_message = other.failure_message
        self.success_message = other.failure_message
        self.event_filters = other.event_filters[:]


class Build(object):
    def __init__(self, job, uuid):
        self.job = job
        self.uuid = uuid
        self.url = None
        self.number = None
        self.result = None
        self.build_set = None
        self.launch_time = time.time()

    def __repr__(self):
        return '<Build %s of %s>' % (self.uuid, self.job.name)


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


class Project(object):
    def __init__(self, name):
        self.name = name
        self.job_trees = {}  # Queue -> JobTree

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Project %s>' % (self.name)

    def addQueue(self, name):
        self.job_trees[name] = JobTree(None)
        return self.job_trees[name]

    def hasQueue(self, name):
        if name in self.job_trees:
            return True
        return False

    def getJobTreeForQueue(self, name):
        return self.job_trees.get(name, None)

    def getJobs(self, queue_name):
        tree = self.getJobTreeForQueue(queue_name)
        if not tree:
            return []
        return tree.getJobs()


class BuildSet(object):
    def __init__(self):
        self.builds = {}

    def addBuild(self, build):
        self.builds[build.job.name] = build
        build.build_set = self

    def getBuild(self, job_name):
        return self.builds.get(job_name)


class Change(object):
    def __init__(self, queue_name, project, event):
        self.queue_name = queue_name
        self.project = project
        self.branch = None
        self.number = None
        self.url = None
        self.patchset = None
        self.refspec = None
        self.ref = None
        self.oldrev = None
        self.newrev = None

        if event.change_number:
            self.branch = event.branch
            self.number = event.change_number
            self.url = event.change_url
            self.patchset = event.patch_number
            self.refspec = event.refspec
        if event.ref:
            self.ref = event.ref
            self.oldrev = event.oldrev
            self.newrev = event.newrev

        self.build_sets = []
        self.current_build_set = BuildSet()
        self.build_sets.append(self.current_build_set)
        self.change_ahead = None
        self.change_behind = None

    def _id(self):
        if self.number:
            return '%s,%s' % (self.number, self.patchset)
        return self.newrev

    def __repr__(self):
        return '<Change 0x%x %s>' % (id(self), self._id())

    def formatStatus(self, indent=0, html=False):
        indent_str = ' ' * indent
        ret = ''
        if html and self.url is not None:
            ret += '%sProject %s change <a href="%s">%s</a>\n' % (indent_str,
                                                            self.project.name,
                                                            self.url,
                                                            self._id())
        else:
            ret += '%sProject %s change %s\n' % (indent_str,
                                                 self.project.name,
                                                 self._id())
        for job in self.project.getJobs(self.queue_name):
            build = self.current_build_set.getBuild(job.name)
            if build:
                result = build.result
            else:
                result = None
            job_name = job.name
            if html:
                if build:
                    url = build.url
                else:
                    url = None
                if url is not None:
                    job_name = '<a href="%s">%s</a>' % (url, job_name)
            ret += '%s  %s: %s' % (indent_str, job_name, result)
            ret += '\n'
        if self.change_ahead:
            ret += '%sWaiting on:\n' % (indent_str)
            ret += self.change_ahead.formatStatus(indent + 2, html)
        return ret

    def formatReport(self):
        ret = ''
        if self.didAllJobsSucceed():
            ret += 'Build successful\n\n'
        else:
            ret += 'Build failed\n\n'

        for job in self.project.getJobs(self.queue_name):
            build = self.current_build_set.getBuild(job.name)
            result = build.result
            url = build.url
            if not url:
                url = job.name
            ret += '- %s : %s\n' % (url, result)
        return ret

    def resetAllBuilds(self):
        self.current_build_set = BuildSet()
        self.build_sets.append(self.current_build_set)

    def addBuild(self, build):
        self.current_build_set.addBuild(build)

    def setResult(self, build):
        if build.result != 'SUCCESS':
            # Get a JobTree from a Job so we can find only its dependent jobs
            root = self.project.getJobTreeForQueue(self.queue_name)
            tree = root.getJobTreeForJob(build.job)
            for job in tree.getJobs():
                fakebuild = Build(job, None)
                fakebuild.result = 'SKIPPED'
                self.addBuild(fakebuild)

    def _findJobsToRun(self, job_trees):
        torun = []
        for tree in job_trees:
            job = tree.job
            result = None
            if job:
                build = self.current_build_set.getBuild(job.name)
                if build:
                    result = build.result
                else:
                    # There is no build for the root of this job tree,
                    # so we should run it.
                    torun.append(job)
            # If there is no job, this is a null job tree, and we should
            # run all of its jobs.
            if result == 'SUCCESS' or not job:
                torun.extend(self._findJobsToRun(tree.job_trees))
        return torun

    def findJobsToRun(self):
        tree = self.project.getJobTreeForQueue(self.queue_name)
        if not tree:
            return []
        return self._findJobsToRun(tree.job_trees)

    def areAllJobsComplete(self):
        tree = self.project.getJobTreeForQueue(self.queue_name)
        for job in tree.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if not build or not build.result:
                return False
        return True

    def didAllJobsSucceed(self):
        tree = self.project.getJobTreeForQueue(self.queue_name)
        for job in tree.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if not build:
                return False
            if build.result != 'SUCCESS':
                return False
        return True

    def delete(self):
        if self.change_behind:
            self.change_behind.change_ahead = None


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
        self.newrew = None

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


class EventFilter(object):
    def __init__(self, types=[], branches=[], refs=[], approvals=[],
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
