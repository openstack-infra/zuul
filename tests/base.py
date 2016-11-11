#!/usr/bin/env python

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

from six.moves import configparser as ConfigParser
import gc
import hashlib
import json
import logging
import os
import pprint
from six.moves import queue as Queue
from six.moves import urllib
import random
import re
import select
import shutil
from six.moves import reload_module
import socket
import string
import subprocess
import swiftclient
import tempfile
import threading
import time

import git
import gear
import fixtures
import statsd
import testtools
from git import GitCommandError

import zuul.connection.gerrit
import zuul.connection.smtp
import zuul.scheduler
import zuul.webapp
import zuul.rpclistener
import zuul.launcher.server
import zuul.launcher.client
import zuul.lib.swift
import zuul.lib.connections
import zuul.merger.client
import zuul.merger.merger
import zuul.merger.server
import zuul.nodepool
import zuul.reporter.gerrit
import zuul.reporter.smtp
import zuul.source.gerrit
import zuul.trigger.gerrit
import zuul.trigger.timer
import zuul.trigger.zuultrigger

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
USE_TEMPDIR = True

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


def repack_repo(path):
    cmd = ['git', '--git-dir=%s/.git' % path, 'repack', '-afd']
    output = subprocess.Popen(cmd, close_fds=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    out = output.communicate()
    if output.returncode:
        raise Exception("git repack returned %d" % output.returncode)
    return out


def random_sha1():
    return hashlib.sha1(str(random.random())).hexdigest()


def iterate_timeout(max_seconds, purpose):
    start = time.time()
    count = 0
    while (time.time() < start + max_seconds):
        count += 1
        yield count
        time.sleep(0)
    raise Exception("Timeout waiting for %s" % purpose)


class ChangeReference(git.Reference):
    _common_path_default = "refs/changes"
    _points_to_commits_only = True


class FakeChange(object):
    categories = {'approved': ('Approved', -1, 1),
                  'code-review': ('Code-Review', -2, 2),
                  'verified': ('Verified', -2, 2)}

    def __init__(self, gerrit, number, project, branch, subject,
                 status='NEW', upstream_root=None, files={}):
        self.gerrit = gerrit
        self.reported = 0
        self.queried = 0
        self.patchsets = []
        self.number = number
        self.project = project
        self.branch = branch
        self.subject = subject
        self.latest_patchset = 0
        self.depends_on_change = None
        self.needed_by_changes = []
        self.fail_merge = False
        self.messages = []
        self.data = {
            'branch': branch,
            'comments': [],
            'commitMessage': subject,
            'createdOn': time.time(),
            'id': 'I' + random_sha1(),
            'lastUpdated': time.time(),
            'number': str(number),
            'open': status == 'NEW',
            'owner': {'email': 'user@example.com',
                      'name': 'User Name',
                      'username': 'username'},
            'patchSets': self.patchsets,
            'project': project,
            'status': status,
            'subject': subject,
            'submitRecords': [],
            'url': 'https://hostname/%s' % number}

        self.upstream_root = upstream_root
        self.addPatchset(files=files)
        self.data['submitRecords'] = self.getSubmitRecords()
        self.open = status == 'NEW'

    def addFakeChangeToRepo(self, msg, files, large):
        path = os.path.join(self.upstream_root, self.project)
        repo = git.Repo(path)
        ref = ChangeReference.create(repo, '1/%s/%s' % (self.number,
                                                        self.latest_patchset),
                                     'refs/tags/init')
        repo.head.reference = ref
        zuul.merger.merger.reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')

        path = os.path.join(self.upstream_root, self.project)
        if not large:
            for fn, content in files.items():
                fn = os.path.join(path, fn)
                with open(fn, 'w') as f:
                    f.write(content)
                repo.index.add([fn])
        else:
            for fni in range(100):
                fn = os.path.join(path, str(fni))
                f = open(fn, 'w')
                for ci in range(4096):
                    f.write(random.choice(string.printable))
                f.close()
                repo.index.add([fn])

        r = repo.index.commit(msg)
        repo.head.reference = 'master'
        zuul.merger.merger.reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')
        repo.heads['master'].checkout()
        return r

    def addPatchset(self, files=None, large=False):
        self.latest_patchset += 1
        if not files:
            fn = '%s-%s' % (self.branch.replace('/', '_'), self.number)
            data = ("test %s %s %s\n" %
                    (self.branch, self.number, self.latest_patchset))
            files = {fn: data}
        msg = self.subject + '-' + str(self.latest_patchset)
        c = self.addFakeChangeToRepo(msg, files, large)
        ps_files = [{'file': '/COMMIT_MSG',
                     'type': 'ADDED'},
                    {'file': 'README',
                     'type': 'MODIFIED'}]
        for f in files.keys():
            ps_files.append({'file': f, 'type': 'ADDED'})
        d = {'approvals': [],
             'createdOn': time.time(),
             'files': ps_files,
             'number': str(self.latest_patchset),
             'ref': 'refs/changes/1/%s/%s' % (self.number,
                                              self.latest_patchset),
             'revision': c.hexsha,
             'uploader': {'email': 'user@example.com',
                          'name': 'User name',
                          'username': 'user'}}
        self.data['currentPatchSet'] = d
        self.patchsets.append(d)
        self.data['submitRecords'] = self.getSubmitRecords()

    def getPatchsetCreatedEvent(self, patchset):
        event = {"type": "patchset-created",
                 "change": {"project": self.project,
                            "branch": self.branch,
                            "id": "I5459869c07352a31bfb1e7a8cac379cabfcb25af",
                            "number": str(self.number),
                            "subject": self.subject,
                            "owner": {"name": "User Name"},
                            "url": "https://hostname/3"},
                 "patchSet": self.patchsets[patchset - 1],
                 "uploader": {"name": "User Name"}}
        return event

    def getChangeRestoredEvent(self):
        event = {"type": "change-restored",
                 "change": {"project": self.project,
                            "branch": self.branch,
                            "id": "I5459869c07352a31bfb1e7a8cac379cabfcb25af",
                            "number": str(self.number),
                            "subject": self.subject,
                            "owner": {"name": "User Name"},
                            "url": "https://hostname/3"},
                 "restorer": {"name": "User Name"},
                 "patchSet": self.patchsets[-1],
                 "reason": ""}
        return event

    def getChangeAbandonedEvent(self):
        event = {"type": "change-abandoned",
                 "change": {"project": self.project,
                            "branch": self.branch,
                            "id": "I5459869c07352a31bfb1e7a8cac379cabfcb25af",
                            "number": str(self.number),
                            "subject": self.subject,
                            "owner": {"name": "User Name"},
                            "url": "https://hostname/3"},
                 "abandoner": {"name": "User Name"},
                 "patchSet": self.patchsets[-1],
                 "reason": ""}
        return event

    def getChangeCommentEvent(self, patchset):
        event = {"type": "comment-added",
                 "change": {"project": self.project,
                            "branch": self.branch,
                            "id": "I5459869c07352a31bfb1e7a8cac379cabfcb25af",
                            "number": str(self.number),
                            "subject": self.subject,
                            "owner": {"name": "User Name"},
                            "url": "https://hostname/3"},
                 "patchSet": self.patchsets[patchset - 1],
                 "author": {"name": "User Name"},
                 "approvals": [{"type": "code-review",
                                "description": "Code-Review",
                                "value": "0"}],
                 "comment": "This is a comment"}
        return event

    def addApproval(self, category, value, username='reviewer_john',
                    granted_on=None, message=''):
        if not granted_on:
            granted_on = time.time()
        approval = {
            'description': self.categories[category][0],
            'type': category,
            'value': str(value),
            'by': {
                'username': username,
                'email': username + '@example.com',
            },
            'grantedOn': int(granted_on)
        }
        for i, x in enumerate(self.patchsets[-1]['approvals'][:]):
            if x['by']['username'] == username and x['type'] == category:
                del self.patchsets[-1]['approvals'][i]
        self.patchsets[-1]['approvals'].append(approval)
        event = {'approvals': [approval],
                 'author': {'email': 'author@example.com',
                            'name': 'Patchset Author',
                            'username': 'author_phil'},
                 'change': {'branch': self.branch,
                            'id': 'Iaa69c46accf97d0598111724a38250ae76a22c87',
                            'number': str(self.number),
                            'owner': {'email': 'owner@example.com',
                                      'name': 'Change Owner',
                                      'username': 'owner_jane'},
                            'project': self.project,
                            'subject': self.subject,
                            'topic': 'master',
                            'url': 'https://hostname/459'},
                 'comment': message,
                 'patchSet': self.patchsets[-1],
                 'type': 'comment-added'}
        self.data['submitRecords'] = self.getSubmitRecords()
        return json.loads(json.dumps(event))

    def getSubmitRecords(self):
        status = {}
        for cat in self.categories.keys():
            status[cat] = 0

        for a in self.patchsets[-1]['approvals']:
            cur = status[a['type']]
            cat_min, cat_max = self.categories[a['type']][1:]
            new = int(a['value'])
            if new == cat_min:
                cur = new
            elif abs(new) > abs(cur):
                cur = new
            status[a['type']] = cur

        labels = []
        ok = True
        for typ, cat in self.categories.items():
            cur = status[typ]
            cat_min, cat_max = cat[1:]
            if cur == cat_min:
                value = 'REJECT'
                ok = False
            elif cur == cat_max:
                value = 'OK'
            else:
                value = 'NEED'
                ok = False
            labels.append({'label': cat[0], 'status': value})
        if ok:
            return [{'status': 'OK'}]
        return [{'status': 'NOT_READY',
                 'labels': labels}]

    def setDependsOn(self, other, patchset):
        self.depends_on_change = other
        d = {'id': other.data['id'],
             'number': other.data['number'],
             'ref': other.patchsets[patchset - 1]['ref']
             }
        self.data['dependsOn'] = [d]

        other.needed_by_changes.append(self)
        needed = other.data.get('neededBy', [])
        d = {'id': self.data['id'],
             'number': self.data['number'],
             'ref': self.patchsets[patchset - 1]['ref'],
             'revision': self.patchsets[patchset - 1]['revision']
             }
        needed.append(d)
        other.data['neededBy'] = needed

    def query(self):
        self.queried += 1
        d = self.data.get('dependsOn')
        if d:
            d = d[0]
            if (self.depends_on_change.patchsets[-1]['ref'] == d['ref']):
                d['isCurrentPatchSet'] = True
            else:
                d['isCurrentPatchSet'] = False
        return json.loads(json.dumps(self.data))

    def setMerged(self):
        if (self.depends_on_change and
                self.depends_on_change.data['status'] != 'MERGED'):
            return
        if self.fail_merge:
            return
        self.data['status'] = 'MERGED'
        self.open = False

        path = os.path.join(self.upstream_root, self.project)
        repo = git.Repo(path)
        repo.heads[self.branch].commit = \
            repo.commit(self.patchsets[-1]['revision'])

    def setReported(self):
        self.reported += 1


class FakeGerritConnection(zuul.connection.gerrit.GerritConnection):
    """A Fake Gerrit connection for use in tests.

    This subclasses
    :py:class:`~zuul.connection.gerrit.GerritConnection` to add the
    ability for tests to add changes to the fake Gerrit it represents.
    """

    log = logging.getLogger("zuul.test.FakeGerritConnection")

    def __init__(self, connection_name, connection_config,
                 changes_db=None, upstream_root=None):
        super(FakeGerritConnection, self).__init__(connection_name,
                                                   connection_config)

        self.event_queue = Queue.Queue()
        self.fixture_dir = os.path.join(FIXTURE_DIR, 'gerrit')
        self.change_number = 0
        self.changes = changes_db
        self.queries = []
        self.upstream_root = upstream_root

    def addFakeChange(self, project, branch, subject, status='NEW',
                      files=None):
        """Add a change to the fake Gerrit."""
        self.change_number += 1
        c = FakeChange(self, self.change_number, project, branch, subject,
                       upstream_root=self.upstream_root,
                       status=status, files=files)
        self.changes[self.change_number] = c
        return c

    def review(self, project, changeid, message, action):
        number, ps = changeid.split(',')
        change = self.changes[int(number)]

        # Add the approval back onto the change (ie simulate what gerrit would
        # do).
        # Usually when zuul leaves a review it'll create a feedback loop where
        # zuul's review enters another gerrit event (which is then picked up by
        # zuul). However, we can't mimic this behaviour (by adding this
        # approval event into the queue) as it stops jobs from checking what
        # happens before this event is triggered. If a job needs to see what
        # happens they can add their own verified event into the queue.
        # Nevertheless, we can update change with the new review in gerrit.

        for cat in action.keys():
            if cat != 'submit':
                change.addApproval(cat, action[cat], username=self.user)

        # TODOv3(jeblair): can this be removed?
        if 'label' in action:
            parts = action['label'].split('=')
            change.addApproval(parts[0], parts[2], username=self.user)

        change.messages.append(message)

        if 'submit' in action:
            change.setMerged()
        if message:
            change.setReported()

    def query(self, number):
        change = self.changes.get(int(number))
        if change:
            return change.query()
        return {}

    def simpleQuery(self, query):
        self.log.debug("simpleQuery: %s" % query)
        self.queries.append(query)
        if query.startswith('change:'):
            # Query a specific changeid
            changeid = query[len('change:'):]
            l = [change.query() for change in self.changes.values()
                 if change.data['id'] == changeid]
        elif query.startswith('message:'):
            # Query the content of a commit message
            msg = query[len('message:'):].strip()
            l = [change.query() for change in self.changes.values()
                 if msg in change.data['commitMessage']]
        else:
            # Query all open changes
            l = [change.query() for change in self.changes.values()]
        return l

    def _start_watcher_thread(self, *args, **kw):
        pass

    def getGitUrl(self, project):
        return os.path.join(self.upstream_root, project.name)


class BuildHistory(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):
        return ("<Completed build, result: %s name: %s uuid: %s changes: %s>" %
                (self.result, self.name, self.uuid, self.changes))


class FakeURLOpener(object):
    def __init__(self, upstream_root, url):
        self.upstream_root = upstream_root
        self.url = url

    def read(self):
        res = urllib.parse.urlparse(self.url)
        path = res.path
        project = '/'.join(path.split('/')[2:-2])
        ret = '001e# service=git-upload-pack\n'
        ret += ('000000a31270149696713ba7e06f1beb760f20d359c4abed HEAD\x00'
                'multi_ack thin-pack side-band side-band-64k ofs-delta '
                'shallow no-progress include-tag multi_ack_detailed no-done\n')
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo(path)
        for ref in repo.refs:
            r = ref.object.hexsha + ' ' + ref.path + '\n'
            ret += '%04x%s' % (len(r) + 4, r)
        ret += '0000'
        return ret


class FakeStatsd(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', 0))
        self.port = self.sock.getsockname()[1]
        self.wake_read, self.wake_write = os.pipe()
        self.stats = []

    def run(self):
        while True:
            poll = select.poll()
            poll.register(self.sock, select.POLLIN)
            poll.register(self.wake_read, select.POLLIN)
            ret = poll.poll()
            for (fd, event) in ret:
                if fd == self.sock.fileno():
                    data = self.sock.recvfrom(1024)
                    if not data:
                        return
                    self.stats.append(data[0])
                if fd == self.wake_read:
                    return

    def stop(self):
        os.write(self.wake_write, '1\n')


class FakeBuild(object):
    log = logging.getLogger("zuul.test")

    def __init__(self, launch_server, job):
        self.daemon = True
        self.launch_server = launch_server
        self.job = job
        self.jobdir = None
        self.uuid = job.unique
        self.parameters = json.loads(job.arguments)
        # TODOv3(jeblair): self.node is really "the image of the node
        # assigned".  We should rename it (self.node_image?) if we
        # keep using it like this, or we may end up exposing more of
        # the complexity around multi-node jobs here
        # (self.nodes[0].image?)
        self.node = None
        if len(self.parameters.get('nodes')) == 1:
            self.node = self.parameters['nodes'][0]['image']
        self.unique = self.parameters['ZUUL_UUID']
        self.name = self.parameters['job']
        self.wait_condition = threading.Condition()
        self.waiting = False
        self.aborted = False
        self.created = time.time()
        self.run_error = False
        self.changes = None
        if 'ZUUL_CHANGE_IDS' in self.parameters:
            self.changes = self.parameters['ZUUL_CHANGE_IDS']

    def __repr__(self):
        waiting = ''
        if self.waiting:
            waiting = ' [waiting]'
        return '<FakeBuild %s %s%s>' % (self.name, self.changes, waiting)

    def release(self):
        """Release this build."""
        self.wait_condition.acquire()
        self.wait_condition.notify()
        self.waiting = False
        self.log.debug("Build %s released" % self.unique)
        self.wait_condition.release()

    def isWaiting(self):
        """Return whether this build is being held.

        :returns: Whether the build is being held.
        :rtype: bool
        """

        self.wait_condition.acquire()
        if self.waiting:
            ret = True
        else:
            ret = False
        self.wait_condition.release()
        return ret

    def _wait(self):
        self.wait_condition.acquire()
        self.waiting = True
        self.log.debug("Build %s waiting" % self.unique)
        self.wait_condition.wait()
        self.wait_condition.release()

    def run(self):
        self.log.debug('Running build %s' % self.unique)

        if self.launch_server.hold_jobs_in_build:
            self.log.debug('Holding build %s' % self.unique)
            self._wait()
        self.log.debug("Build %s continuing" % self.unique)

        result = 'SUCCESS'
        if (('ZUUL_REF' in self.parameters) and self.shouldFail()):
            result = 'FAILURE'
        if self.aborted:
            result = 'ABORTED'

        if self.run_error:
            result = 'RUN_ERROR'

        return result

    def shouldFail(self):
        changes = self.launch_server.fail_tests.get(self.name, [])
        for change in changes:
            if self.hasChanges(change):
                return True
        return False

    def hasChanges(self, *changes):
        """Return whether this build has certain changes in its git repos.

        :arg FakeChange changes: One or more changes (varargs) that
        are expected to be present (in order) in the git repository of
        the active project.

        :returns: Whether the build has the indicated changes.
        :rtype: bool

        """
        project = self.parameters['ZUUL_PROJECT']
        path = os.path.join(self.jobdir.git_root, project)
        repo = git.Repo(path)
        ref = self.parameters['ZUUL_REF']
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        commit_messages = ['%s-1' % change.subject for change in changes]
        self.log.debug("Checking if build %s has changes; commit_messages %s;"
                       " repo_messages %s" % (self, commit_messages,
                                              repo_messages))
        for msg in commit_messages:
            if msg not in repo_messages:
                self.log.debug("  messages do not match")
                return False
        self.log.debug("  OK")
        return True


class RecordingLaunchServer(zuul.launcher.server.LaunchServer):
    """An Ansible launcher to be used in tests.

    :ivar bool hold_jobs_in_build: If true, when jobs are launched
        they will report that they have started but then pause until
        released before reporting completion.  This attribute may be
        changed at any time and will take effect for subsequently
        launched builds, but previously held builds will still need to
        be explicitly released.

    """
    def __init__(self, *args, **kw):
        self._run_ansible = kw.pop('_run_ansible', False)
        super(RecordingLaunchServer, self).__init__(*args, **kw)
        self.hold_jobs_in_build = False
        self.lock = threading.Lock()
        self.running_builds = []
        self.build_history = []
        self.fail_tests = {}
        self.job_builds = {}

    def failJob(self, name, change):
        """Instruct the launcher to report matching builds as failures.

        :arg str name: The name of the job to fail.
        :arg Change change: The :py:class:`~tests.base.FakeChange`
            instance which should cause the job to fail.  This job
            will also fail for changes depending on this change.

        """
        l = self.fail_tests.get(name, [])
        l.append(change)
        self.fail_tests[name] = l

    def release(self, regex=None):
        """Release a held build.

        :arg str regex: A regular expression which, if supplied, will
            cause only builds with matching names to be released.  If
            not supplied, all builds will be released.

        """
        builds = self.running_builds[:]
        self.log.debug("Releasing build %s (%s)" % (regex,
                                                    len(self.running_builds)))
        for build in builds:
            if not regex or re.match(regex, build.name):
                self.log.debug("Releasing build %s" %
                               (build.parameters['ZUUL_UUID']))
                build.release()
            else:
                self.log.debug("Not releasing build %s" %
                               (build.parameters['ZUUL_UUID']))
        self.log.debug("Done releasing builds %s (%s)" %
                       (regex, len(self.running_builds)))

    def launchJob(self, job):
        build = FakeBuild(self, job)
        job.build = build
        self.running_builds.append(build)
        self.job_builds[job.unique] = build
        super(RecordingLaunchServer, self).launchJob(job)

    def stopJob(self, job):
        self.log.debug("handle stop")
        parameters = json.loads(job.arguments)
        uuid = parameters['uuid']
        for build in self.running_builds:
            if build.unique == uuid:
                build.aborted = True
                build.release()
        super(RecordingLaunchServer, self).stopJob(job)

    def runAnsible(self, jobdir, job):
        build = self.job_builds[job.unique]
        build.jobdir = jobdir

        if self._run_ansible:
            result = super(RecordingLaunchServer, self).runAnsible(jobdir, job)
        else:
            result = build.run()

        self.lock.acquire()
        self.build_history.append(
            BuildHistory(name=build.name, result=result, changes=build.changes,
                         node=build.node, uuid=build.unique,
                         parameters=build.parameters,
                         pipeline=build.parameters['ZUUL_PIPELINE'])
        )
        self.running_builds.remove(build)
        del self.job_builds[job.unique]
        self.lock.release()
        return result


class FakeGearmanServer(gear.Server):
    """A Gearman server for use in tests.

    :ivar bool hold_jobs_in_queue: If true, submitted jobs will be
        added to the queue but will not be distributed to workers
        until released.  This attribute may be changed at any time and
        will take effect for subsequently enqueued jobs, but
        previously held jobs will still need to be explicitly
        released.

    """

    def __init__(self):
        self.hold_jobs_in_queue = False
        super(FakeGearmanServer, self).__init__(0)

    def getJobForConnection(self, connection, peek=False):
        for queue in [self.high_queue, self.normal_queue, self.low_queue]:
            for job in queue:
                if not hasattr(job, 'waiting'):
                    if job.name.startswith('launcher:launch'):
                        job.waiting = self.hold_jobs_in_queue
                    else:
                        job.waiting = False
                if job.waiting:
                    continue
                if job.name in connection.functions:
                    if not peek:
                        queue.remove(job)
                        connection.related_jobs[job.handle] = job
                        job.worker_connection = connection
                    job.running = True
                    return job
        return None

    def release(self, regex=None):
        """Release a held job.

        :arg str regex: A regular expression which, if supplied, will
            cause only jobs with matching names to be released.  If
            not supplied, all jobs will be released.
        """
        released = False
        qlen = (len(self.high_queue) + len(self.normal_queue) +
                len(self.low_queue))
        self.log.debug("releasing queued job %s (%s)" % (regex, qlen))
        for job in self.getQueue():
            if job.name != 'launcher:launch':
                continue
            parameters = json.loads(job.arguments)
            if not regex or re.match(regex, parameters.get('job')):
                self.log.debug("releasing queued job %s" %
                               job.unique)
                job.waiting = False
                released = True
            else:
                self.log.debug("not releasing queued job %s" %
                               job.unique)
        if released:
            self.wakeConnections()
        qlen = (len(self.high_queue) + len(self.normal_queue) +
                len(self.low_queue))
        self.log.debug("done releasing queued jobs %s (%s)" % (regex, qlen))


class FakeSMTP(object):
    log = logging.getLogger('zuul.FakeSMTP')

    def __init__(self, messages, server, port):
        self.server = server
        self.port = port
        self.messages = messages

    def sendmail(self, from_email, to_email, msg):
        self.log.info("Sending email from %s, to %s, with msg %s" % (
                      from_email, to_email, msg))

        headers = msg.split('\n\n', 1)[0]
        body = msg.split('\n\n', 1)[1]

        self.messages.append(dict(
            from_email=from_email,
            to_email=to_email,
            msg=msg,
            headers=headers,
            body=body,
        ))

        return True

    def quit(self):
        return True


class FakeSwiftClientConnection(swiftclient.client.Connection):
    def post_account(self, headers):
        # Do nothing
        pass

    def get_auth(self):
        # Returns endpoint and (unused) auth token
        endpoint = os.path.join('https://storage.example.org', 'V1',
                                'AUTH_account')
        return endpoint, ''


class BaseTestCase(testtools.TestCase):
    log = logging.getLogger("zuul.test")

    def setUp(self):
        super(BaseTestCase, self).setUp()
        test_timeout = os.environ.get('OS_TEST_TIMEOUT', 0)
        try:
            test_timeout = int(test_timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=False))

        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
            os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
            os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))
        if (os.environ.get('OS_LOG_CAPTURE') == 'True' or
            os.environ.get('OS_LOG_CAPTURE') == '1'):
            self.useFixture(fixtures.FakeLogger(
                level=logging.DEBUG,
                format='%(asctime)s %(name)-32s '
                '%(levelname)-8s %(message)s'))

            # NOTE(notmorgan): Extract logging overrides for specific libraries
            # from the OS_LOG_DEFAULTS env and create FakeLogger fixtures for
            # each. This is used to limit the output during test runs from
            # libraries that zuul depends on such as gear.
            log_defaults_from_env = os.environ.get('OS_LOG_DEFAULTS')

            if log_defaults_from_env:
                for default in log_defaults_from_env.split(','):
                    try:
                        name, level_str = default.split('=', 1)
                        level = getattr(logging, level_str, logging.DEBUG)
                        self.useFixture(fixtures.FakeLogger(
                            name=name,
                            level=level,
                            format='%(asctime)s %(name)-32s '
                                   '%(levelname)-8s %(message)s'))
                    except ValueError:
                        # NOTE(notmorgan): Invalid format of the log default,
                        # skip and don't try and apply a logger for the
                        # specified module
                        pass


class ZuulTestCase(BaseTestCase):
    """A test case with a functioning Zuul.

    The following class variables are used during test setup and can
    be overidden by subclasses but are effectively read-only once a
    test method starts running:

    :cvar str config_file: This points to the main zuul config file
        within the fixtures directory.  Subclasses may override this
        to obtain a different behavior.

    :cvar str tenant_config_file: This is the tenant config file
        (which specifies from what git repos the configuration should
        be loaded).  It defaults to the value specified in
        `config_file` but can be overidden by subclasses to obtain a
        different tenant/project layout while using the standard main
        configuration.

    The following are instance variables that are useful within test
    methods:

    :ivar FakeGerritConnection fake_<connection>:
        A :py:class:`~tests.base.FakeGerritConnection` will be
        instantiated for each connection present in the config file
        and stored here.  For instance, `fake_gerrit` will hold the
        FakeGerritConnection object for a connection named `gerrit`.

    :ivar FakeGearmanServer gearman_server: An instance of
        :py:class:`~tests.base.FakeGearmanServer` which is the Gearman
        server that all of the Zuul components in this test use to
        communicate with each other.

    :ivar RecordingLaunchServer launch_server: An instance of
        :py:class:`~tests.base.RecordingLaunchServer` which is the
        Ansible launch server used to run jobs for this test.

    :ivar list builds: A list of :py:class:`~tests.base.FakeBuild` objects
        representing currently running builds.  They are appended to
        the list in the order they are launched, and removed from this
        list upon completion.

    :ivar list history: A list of :py:class:`~tests.base.BuildHistory`
        objects representing completed builds.  They are appended to
        the list in the order they complete.

    """

    config_file = 'zuul.conf'
    run_ansible = False

    def _startMerger(self):
        self.merge_server = zuul.merger.server.MergeServer(self.config,
                                                           self.connections)
        self.merge_server.start()

    def setUp(self):
        super(ZuulTestCase, self).setUp()
        if USE_TEMPDIR:
            tmp_root = self.useFixture(fixtures.TempDir(
                rootdir=os.environ.get("ZUUL_TEST_ROOT"))
            ).path
        else:
            tmp_root = os.environ.get("ZUUL_TEST_ROOT")
        self.test_root = os.path.join(tmp_root, "zuul-test")
        self.upstream_root = os.path.join(self.test_root, "upstream")
        self.git_root = os.path.join(self.test_root, "git")
        self.state_root = os.path.join(self.test_root, "lib")

        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)
        os.makedirs(self.test_root)
        os.makedirs(self.upstream_root)
        os.makedirs(self.state_root)

        # Make per test copy of Configuration.
        self.setup_config()
        self.config.set('zuul', 'tenant_config',
                        os.path.join(FIXTURE_DIR,
                                     self.config.get('zuul', 'tenant_config')))
        self.config.set('merger', 'git_dir', self.git_root)
        self.config.set('zuul', 'state_dir', self.state_root)

        # For each project in config:
        # TODOv3(jeblair): remove these and replace with new git
        # filesystem fixtures
        self.init_repo("org/project3")
        self.init_repo("org/project4")
        self.init_repo("org/project5")
        self.init_repo("org/project6")
        self.init_repo("org/one-job-project")
        self.init_repo("org/nonvoting-project")
        self.init_repo("org/templated-project")
        self.init_repo("org/layered-project")
        self.init_repo("org/node-project")
        self.init_repo("org/conflict-project")
        self.init_repo("org/noop-project")
        self.init_repo("org/experimental-project")
        self.init_repo("org/no-jobs-project")

        self.statsd = FakeStatsd()
        # note, use 127.0.0.1 rather than localhost to avoid getting ipv6
        # see: https://github.com/jsocol/pystatsd/issues/61
        os.environ['STATSD_HOST'] = '127.0.0.1'
        os.environ['STATSD_PORT'] = str(self.statsd.port)
        self.statsd.start()
        # the statsd client object is configured in the statsd module import
        reload_module(statsd)
        reload_module(zuul.scheduler)

        self.gearman_server = FakeGearmanServer()

        self.config.set('gearman', 'port', str(self.gearman_server.port))

        zuul.source.gerrit.GerritSource.replication_timeout = 1.5
        zuul.source.gerrit.GerritSource.replication_retry_interval = 0.5
        zuul.connection.gerrit.GerritEventConnector.delay = 0.0

        self.sched = zuul.scheduler.Scheduler(self.config)

        self.useFixture(fixtures.MonkeyPatch('swiftclient.client.Connection',
                                             FakeSwiftClientConnection))
        self.swift = zuul.lib.swift.Swift(self.config)

        self.event_queues = [
            self.sched.result_event_queue,
            self.sched.trigger_event_queue
        ]

        self.configure_connections()
        self.sched.registerConnections(self.connections)

        def URLOpenerFactory(*args, **kw):
            if isinstance(args[0], urllib.request.Request):
                return old_urlopen(*args, **kw)
            return FakeURLOpener(self.upstream_root, *args, **kw)

        old_urlopen = urllib.request.urlopen
        urllib.request.urlopen = URLOpenerFactory

        self._startMerger()

        self.launch_server = RecordingLaunchServer(
            self.config, self.connections, _run_ansible=self.run_ansible)
        self.launch_server.start()
        self.history = self.launch_server.build_history
        self.builds = self.launch_server.running_builds

        self.launch_client = zuul.launcher.client.LaunchClient(
            self.config, self.sched, self.swift)
        self.merge_client = zuul.merger.client.MergeClient(
            self.config, self.sched)
        self.nodepool = zuul.nodepool.Nodepool(self.sched)

        self.sched.setLauncher(self.launch_client)
        self.sched.setMerger(self.merge_client)
        self.sched.setNodepool(self.nodepool)

        self.webapp = zuul.webapp.WebApp(
            self.sched, port=0, listen_address='127.0.0.1')
        self.rpc = zuul.rpclistener.RPCListener(self.config, self.sched)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()
        self.webapp.start()
        self.rpc.start()
        self.launch_client.gearman.waitForServer()

        self.addCleanup(self.assertFinalState)
        self.addCleanup(self.shutdown)

    def configure_connections(self):
        # Register connections from the config
        self.smtp_messages = []

        def FakeSMTPFactory(*args, **kw):
            args = [self.smtp_messages] + list(args)
            return FakeSMTP(*args, **kw)

        self.useFixture(fixtures.MonkeyPatch('smtplib.SMTP', FakeSMTPFactory))

        # Set a changes database so multiple FakeGerrit's can report back to
        # a virtual canonical database given by the configured hostname
        self.gerrit_changes_dbs = {}
        self.connections = zuul.lib.connections.ConnectionRegistry()

        for section_name in self.config.sections():
            con_match = re.match(r'^connection ([\'\"]?)(.*)(\1)$',
                                 section_name, re.I)
            if not con_match:
                continue
            con_name = con_match.group(2)
            con_config = dict(self.config.items(section_name))

            if 'driver' not in con_config:
                raise Exception("No driver specified for connection %s."
                                % con_name)

            con_driver = con_config['driver']

            # TODO(jhesketh): load the required class automatically
            if con_driver == 'gerrit':
                if con_config['server'] not in self.gerrit_changes_dbs.keys():
                    self.gerrit_changes_dbs[con_config['server']] = {}
                self.connections.connections[con_name] = FakeGerritConnection(
                    con_name, con_config,
                    changes_db=self.gerrit_changes_dbs[con_config['server']],
                    upstream_root=self.upstream_root
                )
                self.event_queues.append(
                    self.connections.connections[con_name].event_queue)
                setattr(self, 'fake_' + con_name,
                        self.connections.connections[con_name])
            elif con_driver == 'smtp':
                self.connections.connections[con_name] = \
                    zuul.connection.smtp.SMTPConnection(con_name, con_config)
            else:
                raise Exception("Unknown driver, %s, for connection %s"
                                % (con_config['driver'], con_name))

        # If the [gerrit] or [smtp] sections still exist, load them in as a
        # connection named 'gerrit' or 'smtp' respectfully

        if 'gerrit' in self.config.sections():
            self.gerrit_changes_dbs['gerrit'] = {}
            self.event_queues.append(
                self.connections.connections[con_name].event_queue)
            self.connections.connections['gerrit'] = FakeGerritConnection(
                '_legacy_gerrit', dict(self.config.items('gerrit')),
                changes_db=self.gerrit_changes_dbs['gerrit'])

        if 'smtp' in self.config.sections():
            self.connections.connections['smtp'] = \
                zuul.connection.smtp.SMTPConnection(
                    '_legacy_smtp', dict(self.config.items('smtp')))

    def setup_config(self):
        # This creates the per-test configuration object.  It can be
        # overriden by subclasses, but should not need to be since it
        # obeys the config_file and tenant_config_file attributes.
        self.config = ConfigParser.ConfigParser()
        self.config.read(os.path.join(FIXTURE_DIR, self.config_file))
        if hasattr(self, 'tenant_config_file'):
            self.config.set('zuul', 'tenant_config', self.tenant_config_file)
            git_path = os.path.join(
                os.path.dirname(
                    os.path.join(FIXTURE_DIR, self.tenant_config_file)),
                'git')
            if os.path.exists(git_path):
                for reponame in os.listdir(git_path):
                    project = reponame.replace('_', '/')
                    self.copyDirToRepo(project,
                                       os.path.join(git_path, reponame))

    def copyDirToRepo(self, project, source_path):
        self.init_repo(project)

        files = {}
        for (dirpath, dirnames, filenames) in os.walk(source_path):
            for filename in filenames:
                test_tree_filepath = os.path.join(dirpath, filename)
                common_path = os.path.commonprefix([test_tree_filepath,
                                                    source_path])
                relative_filepath = test_tree_filepath[len(common_path) + 1:]
                with open(test_tree_filepath, 'r') as f:
                    content = f.read()
                files[relative_filepath] = content
        self.addCommitToRepo(project, 'add content from fixture',
                             files, branch='master', tag='init')

    def assertFinalState(self):
        # Make sure that git.Repo objects have been garbage collected.
        repos = []
        gc.collect()
        for obj in gc.get_objects():
            if isinstance(obj, git.Repo):
                repos.append(obj)
        self.assertEqual(len(repos), 0)
        self.assertEmptyQueues()
        ipm = zuul.manager.independent.IndependentPipelineManager
        for tenant in self.sched.abide.tenants.values():
            for pipeline in tenant.layout.pipelines.values():
                if isinstance(pipeline.manager, ipm):
                    self.assertEqual(len(pipeline.queues), 0)

    def shutdown(self):
        self.log.debug("Shutting down after tests")
        self.launch_client.stop()
        self.merge_server.stop()
        self.merge_server.join()
        self.merge_client.stop()
        self.launch_server.stop()
        self.sched.stop()
        self.sched.join()
        self.statsd.stop()
        self.statsd.join()
        self.webapp.stop()
        self.webapp.join()
        self.rpc.stop()
        self.rpc.join()
        self.gearman_server.shutdown()
        threads = threading.enumerate()
        if len(threads) > 1:
            self.log.error("More than one thread is running: %s" % threads)

    def init_repo(self, project):
        parts = project.split('/')
        path = os.path.join(self.upstream_root, *parts[:-1])
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo.init(path)

        with repo.config_writer() as config_writer:
            config_writer.set_value('user', 'email', 'user@example.com')
            config_writer.set_value('user', 'name', 'User Name')

        repo.index.commit('initial commit')
        master = repo.create_head('master')

        repo.head.reference = master
        zuul.merger.merger.reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')

    def create_branch(self, project, branch):
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo.init(path)
        fn = os.path.join(path, 'README')

        branch_head = repo.create_head(branch)
        repo.head.reference = branch_head
        f = open(fn, 'a')
        f.write("test %s\n" % branch)
        f.close()
        repo.index.add([fn])
        repo.index.commit('%s commit' % branch)

        repo.head.reference = repo.heads['master']
        zuul.merger.merger.reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')

    def create_commit(self, project):
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo(path)
        repo.head.reference = repo.heads['master']
        file_name = os.path.join(path, 'README')
        with open(file_name, 'a') as f:
            f.write('creating fake commit\n')
        repo.index.add([file_name])
        commit = repo.index.commit('Creating a fake commit')
        return commit.hexsha

    def ref_has_change(self, ref, change):
        # TODOv3(jeblair): this should probably be removed in favor of
        # build.hasChanges
        path = os.path.join(self.git_root, change.project)
        repo = git.Repo(path)
        try:
            for commit in repo.iter_commits(ref):
                if commit.message.strip() == ('%s-1' % change.subject):
                    return True
        except GitCommandError:
            pass
        return False

    def orderedRelease(self):
        # Run one build at a time to ensure non-race order:
        while len(self.builds):
            self.release(self.builds[0])
            self.waitUntilSettled()

    def release(self, job):
        if isinstance(job, FakeBuild):
            job.release()
        else:
            job.waiting = False
            self.log.debug("Queued job %s released" % job.unique)
            self.gearman_server.wakeConnections()

    def getParameter(self, job, name):
        if isinstance(job, FakeBuild):
            return job.parameters[name]
        else:
            parameters = json.loads(job.arguments)
            return parameters[name]

    def resetGearmanServer(self):
        self.launch_server.worker.setFunctions([])
        while True:
            done = True
            for connection in self.gearman_server.active_connections:
                if (connection.functions and
                    connection.client_id not in ['Zuul RPC Listener',
                                                 'Zuul Merger']):
                    done = False
            if done:
                break
            time.sleep(0)
        self.gearman_server.functions = set()
        self.rpc.register()

    def haveAllBuildsReported(self):
        # See if Zuul is waiting on a meta job to complete
        if self.launch_client.meta_jobs:
            return False
        # Find out if every build that the worker has completed has been
        # reported back to Zuul.  If it hasn't then that means a Gearman
        # event is still in transit and the system is not stable.
        for build in self.history:
            zbuild = self.launch_client.builds.get(build.uuid)
            if not zbuild:
                # It has already been reported
                continue
            # It hasn't been reported yet.
            return False
        # Make sure that none of the worker connections are in GRAB_WAIT
        for connection in self.launch_server.worker.active_connections:
            if connection.state == 'GRAB_WAIT':
                return False
        return True

    def areAllBuildsWaiting(self):
        builds = self.launch_client.builds.values()
        for build in builds:
            client_job = None
            for conn in self.launch_client.gearman.active_connections:
                for j in conn.related_jobs.values():
                    if j.unique == build.uuid:
                        client_job = j
                        break
            if not client_job:
                self.log.debug("%s is not known to the gearman client" %
                               build)
                return False
            if not client_job.handle:
                self.log.debug("%s has no handle" % client_job)
                return False
            server_job = self.gearman_server.jobs.get(client_job.handle)
            if not server_job:
                self.log.debug("%s is not known to the gearman server" %
                               client_job)
                return False
            if not hasattr(server_job, 'waiting'):
                self.log.debug("%s is being enqueued" % server_job)
                return False
            if server_job.waiting:
                continue
            if build.url is None:
                self.log.debug("%s has not reported start" % build)
                return False
            worker_build = self.launch_server.job_builds.get(server_job.unique)
            if worker_build:
                if worker_build.isWaiting():
                    continue
                else:
                    self.log.debug("%s is running" % worker_build)
                    return False
            else:
                self.log.debug("%s is unassigned" % server_job)
                return False
        return True

    def eventQueuesEmpty(self):
        for queue in self.event_queues:
            yield queue.empty()

    def eventQueuesJoin(self):
        for queue in self.event_queues:
            queue.join()

    def waitUntilSettled(self):
        self.log.debug("Waiting until settled...")
        start = time.time()
        while True:
            if time.time() - start > 10:
                self.log.debug("Queue status:")
                for queue in self.event_queues:
                    self.log.debug("  %s: %s" % (queue, queue.empty()))
                self.log.debug("All builds waiting: %s" %
                               (self.areAllBuildsWaiting(),))
                self.log.debug("All builds reported: %s" %
                               (self.haveAllBuildsReported(),))
                raise Exception("Timeout waiting for Zuul to settle")
            # Make sure no new events show up while we're checking

            self.launch_server.lock.acquire()
            # have all build states propogated to zuul?
            if self.haveAllBuildsReported():
                # Join ensures that the queue is empty _and_ events have been
                # processed
                self.eventQueuesJoin()
                self.sched.run_handler_lock.acquire()
                if (not self.merge_client.jobs and
                    all(self.eventQueuesEmpty()) and
                    self.haveAllBuildsReported() and
                    self.areAllBuildsWaiting()):
                    self.sched.run_handler_lock.release()
                    self.launch_server.lock.release()
                    self.log.debug("...settled.")
                    return
                self.sched.run_handler_lock.release()
            self.launch_server.lock.release()
            self.sched.wake_event.wait(0.1)

    def countJobResults(self, jobs, result):
        jobs = filter(lambda x: x.result == result, jobs)
        return len(jobs)

    def getJobFromHistory(self, name, project=None):
        for job in self.history:
            if (job.name == name and
                (project is None or
                 job.parameters['ZUUL_PROJECT'] == project)):
                return job
        raise Exception("Unable to find job %s in history" % name)

    def assertEmptyQueues(self):
        # Make sure there are no orphaned jobs
        for tenant in self.sched.abide.tenants.values():
            for pipeline in tenant.layout.pipelines.values():
                for queue in pipeline.queues:
                    if len(queue.queue) != 0:
                        print('pipeline %s queue %s contents %s' % (
                            pipeline.name, queue.name, queue.queue))
                    self.assertEqual(len(queue.queue), 0,
                                     "Pipelines queues should be empty")

    def assertReportedStat(self, key, value=None, kind=None):
        start = time.time()
        while time.time() < (start + 5):
            for stat in self.statsd.stats:
                pprint.pprint(self.statsd.stats)
                k, v = stat.split(':')
                if key == k:
                    if value is None and kind is None:
                        return
                    elif value:
                        if value == v:
                            return
                    elif kind:
                        if v.endswith('|' + kind):
                            return
            time.sleep(0.1)

        pprint.pprint(self.statsd.stats)
        raise Exception("Key %s not found in reported stats" % key)

    def assertBuilds(self, builds):
        """Assert that the running builds are as described.

        The list of running builds is examined and must match exactly
        the list of builds described by the input.

        :arg list builds: A list of dictionaries.  Each item in the
            list must match the corresponding build in the build
            history, and each element of the dictionary must match the
            corresponding attribute of the build.

        """
        try:
            self.assertEqual(len(self.builds), len(builds))
            for i, d in enumerate(builds):
                for k, v in d.items():
                    self.assertEqual(
                        getattr(self.builds[i], k), v,
                        "Element %i in builds does not match" % (i,))
        except Exception:
            for build in self.builds:
                self.log.error("Running build: %s" % build)
            else:
                self.log.error("No running builds")
            raise

    def assertHistory(self, history, ordered=True):
        """Assert that the completed builds are as described.

        The list of completed builds is examined and must match
        exactly the list of builds described by the input.

        :arg list history: A list of dictionaries.  Each item in the
            list must match the corresponding build in the build
            history, and each element of the dictionary must match the
            corresponding attribute of the build.

        :arg bool ordered: If true, the history must match the order
            supplied, if false, the builds are permitted to have
            arrived in any order.

        """
        def matches(history_item, item):
            for k, v in item.items():
                if getattr(history_item, k) != v:
                    return False
            return True
        try:
            self.assertEqual(len(self.history), len(history))
            if ordered:
                for i, d in enumerate(history):
                    if not matches(self.history[i], d):
                        raise Exception(
                            "Element %i in history does not match" % (i,))
            else:
                unseen = self.history[:]
                for i, d in enumerate(history):
                    found = False
                    for unseen_item in unseen:
                        if matches(unseen_item, d):
                            found = True
                            unseen.remove(unseen_item)
                            break
                    if not found:
                        raise Exception("No match found for element %i "
                                        "in history" % (i,))
                if unseen:
                    raise Exception("Unexpected items in history")
        except Exception:
            for build in self.history:
                self.log.error("Completed build: %s" % build)
            else:
                self.log.error("No completed builds")
            raise

    def getPipeline(self, name):
        return self.sched.abide.tenants.values()[0].layout.pipelines.get(name)

    def updateConfigLayout(self, path):
        root = os.path.join(self.test_root, "config")
        os.makedirs(root)
        f = tempfile.NamedTemporaryFile(dir=root, delete=False)
        f.write("""
- tenant:
    name: openstack
    source:
      gerrit:
        config-repos:
          - %s
        """ % path)
        f.close()
        self.config.set('zuul', 'tenant_config',
                        os.path.join(FIXTURE_DIR, f.name))

    def addCommitToRepo(self, project, message, files,
                        branch='master', tag=None):
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo(path)
        repo.head.reference = branch
        zuul.merger.merger.reset_repo_to_head(repo)
        for fn, content in files.items():
            fn = os.path.join(path, fn)
            with open(fn, 'w') as f:
                f.write(content)
            repo.index.add([fn])
        commit = repo.index.commit(message)
        repo.heads[branch].commit = commit
        repo.head.reference = branch
        repo.git.clean('-x', '-f', '-d')
        repo.heads[branch].checkout()
        if tag:
            repo.create_tag(tag)

    def addEvent(self, connection, event):
        """Inject a Fake (Gerrit) event.

        This method accepts a JSON-encoded event and simulates Zuul
        having received it from Gerrit.  It could (and should)
        eventually apply to any connection type, but is currently only
        used with Gerrit connections.  The name of the connection is
        used to look up the corresponding server, and the event is
        simulated as having been received by all Zuul connections
        attached to that server.  So if two Gerrit connections in Zuul
        are connected to the same Gerrit server, and you invoke this
        method specifying the name of one of them, the event will be
        received by both.

        .. note::

            "self.fake_gerrit.addEvent" calls should be migrated to
            this method.

        :arg str connection: The name of the connection corresponding
        to the gerrit server.
        :arg str event: The JSON-encoded event.

        """
        specified_conn = self.connections.connections[connection]
        for conn in self.connections.connections.values():
            if (isinstance(conn, specified_conn.__class__) and
                specified_conn.server == conn.server):
                conn.addEvent(event)


class AnsibleZuulTestCase(ZuulTestCase):
    """ZuulTestCase but with an actual ansible launcher running"""
    run_ansible = True
