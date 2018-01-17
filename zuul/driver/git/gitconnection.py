# Copyright 2011 OpenStack, LLC.
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

import os
import git
import time
import logging
import urllib
import threading

import voluptuous as v

from zuul.connection import BaseConnection
from zuul.driver.git.gitmodel import GitTriggerEvent, EMPTY_GIT_REF
from zuul.model import Ref, Branch


class GitWatcher(threading.Thread):
    log = logging.getLogger("connection.git.GitWatcher")

    def __init__(self, git_connection, baseurl, poll_delay):
        threading.Thread.__init__(self)
        self.daemon = True
        self.git_connection = git_connection
        self.baseurl = baseurl
        self.poll_delay = poll_delay
        self._stopped = False
        self.projects_refs = self.git_connection.projects_refs
        # This is used by the test framework
        self._event_count = 0

    def compareRefs(self, project, refs):
        partial_events = []
        # Fetch previous refs state
        base_refs = self.projects_refs.get(project)
        # Create list of created refs
        rcreateds = set(refs.keys()) - set(base_refs.keys())
        # Create list of deleted refs
        rdeleteds = set(base_refs.keys()) - set(refs.keys())
        # Create the list of updated refs
        updateds = {}
        for ref, sha in refs.items():
            if ref in base_refs and base_refs[ref] != sha:
                updateds[ref] = sha
        for ref in rcreateds:
            event = {
                'ref': ref,
                'branch_created': True,
                'oldrev': EMPTY_GIT_REF,
                'newrev': refs[ref]
            }
            partial_events.append(event)
        for ref in rdeleteds:
            event = {
                'ref': ref,
                'branch_deleted': True,
                'oldrev': base_refs[ref],
                'newrev': EMPTY_GIT_REF
            }
            partial_events.append(event)
        for ref, sha in updateds.items():
            event = {
                'ref': ref,
                'branch_updated': True,
                'oldrev': base_refs[ref],
                'newrev': sha
            }
            partial_events.append(event)
        events = []
        for pevent in partial_events:
            event = GitTriggerEvent()
            event.type = 'ref-updated'
            event.project_hostname = self.git_connection.canonical_hostname
            event.project_name = project
            for attr in ('ref', 'oldrev', 'newrev', 'branch_created',
                         'branch_deleted', 'branch_updated'):
                if attr in pevent:
                    setattr(event, attr, pevent[attr])
            events.append(event)
        return events

    def _run(self):
        self.log.debug("Walk through projects refs for connection: %s" %
                       self.git_connection.connection_name)
        try:
            for project in self.git_connection.projects:
                refs = self.git_connection.lsRemote(project)
                self.log.debug("Read refs %s for project %s" % (refs, project))
                if not self.projects_refs.get(project):
                    # State for this project does not exist yet so add it.
                    # No event will be triggered in this loop as
                    # projects_refs['project'] and refs are equal
                    self.projects_refs[project] = refs
                events = self.compareRefs(project, refs)
                self.projects_refs[project] = refs
                # Send events to the scheduler
                for event in events:
                    self.log.debug("Handling event: %s" % event)
                    # Force changes cache update before passing
                    # the event to the scheduler
                    self.git_connection.getChange(event)
                    self.git_connection.logEvent(event)
                    # Pass the event to the scheduler
                    self.git_connection.sched.addEvent(event)
                    self._event_count += 1
        except Exception as e:
            self.log.debug("Unexpected issue in _run loop: %s" % str(e))

    def run(self):
        while not self._stopped:
            if not self.git_connection.w_pause:
                self._run()
                # Polling wait delay
            else:
                self.log.debug("Watcher is on pause")
            time.sleep(self.poll_delay)

    def stop(self):
        self._stopped = True


class GitConnection(BaseConnection):
    driver_name = 'git'
    log = logging.getLogger("connection.git")

    def __init__(self, driver, connection_name, connection_config):
        super(GitConnection, self).__init__(driver, connection_name,
                                            connection_config)
        if 'baseurl' not in self.connection_config:
            raise Exception('baseurl is required for git connections in '
                            '%s' % self.connection_name)
        self.baseurl = self.connection_config.get('baseurl')
        self.poll_timeout = float(
            self.connection_config.get('poll_delay', 3600 * 2))
        self.canonical_hostname = self.connection_config.get(
            'canonical_hostname')
        if not self.canonical_hostname:
            r = urllib.parse.urlparse(self.baseurl)
            if r.hostname:
                self.canonical_hostname = r.hostname
            else:
                self.canonical_hostname = 'localhost'
        self.w_pause = False
        self.projects = {}
        self.projects_refs = {}
        self._change_cache = {}

    def getProject(self, name):
        return self.projects.get(name)

    def addProject(self, project):
        self.projects[project.name] = project

    def getChangeFilesUpdated(self, project_name, branch, tosha):
        job = self.sched.merger.getFilesChanges(
            self.connection_name, project_name, branch, tosha)
        self.log.debug("Waiting for fileschanges job %s" % job)
        job.wait()
        if not job.updated:
            raise Exception("Fileschanges job %s failed" % job)
        self.log.debug("Fileschanges job %s got changes on files %s" %
                       (job, job.files))
        return job.files

    def lsRemote(self, project):
        refs = {}
        client = git.cmd.Git()
        output = client.ls_remote(
            os.path.join(self.baseurl, project))
        for line in output.splitlines():
            sha, ref = line.split('\t')
            if ref.startswith('refs/'):
                refs[ref] = sha
        return refs

    def maintainCache(self, relevant):
        remove = {}
        for branch, refschange in self._change_cache.items():
            for ref, change in refschange.items():
                if change not in relevant:
                    remove.setdefault(branch, []).append(ref)
        for branch, refs in remove.items():
            for ref in refs:
                del self._change_cache[branch][ref]
            if not self._change_cache[branch]:
                del self._change_cache[branch]

    def getChange(self, event, refresh=False):
        if event.ref and event.ref.startswith('refs/heads/'):
            branch = event.ref[len('refs/heads/'):]
            change = self._change_cache.get(branch, {}).get(event.newrev)
            if change:
                return change
            project = self.getProject(event.project_name)
            change = Branch(project)
            change.branch = branch
            for attr in ('ref', 'oldrev', 'newrev'):
                setattr(change, attr, getattr(event, attr))
            change.url = ""
            change.files = self.getChangeFilesUpdated(
                event.project_name, change.branch, event.oldrev)
            self._change_cache.setdefault(branch, {})[event.newrev] = change
        elif event.ref:
            # catch-all ref (ie, not a branch or head)
            project = self.getProject(event.project_name)
            change = Ref(project)
            for attr in ('ref', 'oldrev', 'newrev'):
                setattr(change, attr, getattr(event, attr))
            change.url = ""
        else:
            self.log.warning("Unable to get change for %s" % (event,))
            change = None
        return change

    def getProjectBranches(self, project, tenant):
        refs = self.lsRemote(project.name)
        branches = [ref[len('refs/heads/'):] for ref in
                    refs if ref.startswith('refs/heads/')]
        return branches

    def getGitUrl(self, project):
        url = '%s/%s' % (self.baseurl, project.name)
        return url

    def onLoad(self):
        self.log.debug("Starting Git Watcher")
        self._start_watcher_thread()

    def onStop(self):
        self.log.debug("Stopping Git Watcher")
        self._stop_watcher_thread()

    def _stop_watcher_thread(self):
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.join()

    def _start_watcher_thread(self):
        self.watcher_thread = GitWatcher(
            self,
            self.baseurl,
            self.poll_timeout)
        self.watcher_thread.start()


def getSchema():
    git_connection = v.Any(str, v.Schema(dict))
    return git_connection
