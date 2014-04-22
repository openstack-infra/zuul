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

import ConfigParser
from cStringIO import StringIO
import gc
import gzip
import hashlib
import json
import logging
import os
import pprint
import Queue
import random
import re
import select
import shutil
import socket
import string
import subprocess
import swiftclient
import threading
import time
import urllib
import urllib2

import git
import gear
import fixtures
import six.moves.urllib.parse as urlparse
import statsd
import testtools

import zuul.scheduler
import zuul.webapp
import zuul.rpclistener
import zuul.rpcclient
import zuul.launcher.gearman
import zuul.lib.swift
import zuul.merger.server
import zuul.merger.client
import zuul.reporter.gerrit
import zuul.reporter.smtp
import zuul.trigger.gerrit
import zuul.trigger.timer

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
CONFIG = ConfigParser.ConfigParser()
CONFIG.read(os.path.join(FIXTURE_DIR, "zuul.conf"))

CONFIG.set('zuul', 'layout_config',
           os.path.join(FIXTURE_DIR, "layout.yaml"))

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


class ChangeReference(git.Reference):
    _common_path_default = "refs/changes"
    _points_to_commits_only = True


class FakeChange(object):
    categories = {'APRV': ('Approved', -1, 1),
                  'CRVW': ('Code-Review', -2, 2),
                  'VRFY': ('Verified', -2, 2)}

    def __init__(self, gerrit, number, project, branch, subject,
                 status='NEW', upstream_root=None):
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
            'open': True,
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
        self.addPatchset()
        self.data['submitRecords'] = self.getSubmitRecords()

    def add_fake_change_to_repo(self, msg, fn, large):
        path = os.path.join(self.upstream_root, self.project)
        repo = git.Repo(path)
        ref = ChangeReference.create(repo, '1/%s/%s' % (self.number,
                                                        self.latest_patchset),
                                     'refs/tags/init')
        repo.head.reference = ref
        repo.head.reset(index=True, working_tree=True)
        repo.git.clean('-x', '-f', '-d')

        path = os.path.join(self.upstream_root, self.project)
        if not large:
            fn = os.path.join(path, fn)
            f = open(fn, 'w')
            f.write("test %s %s %s\n" %
                    (self.branch, self.number, self.latest_patchset))
            f.close()
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
        repo.head.reset(index=True, working_tree=True)
        repo.git.clean('-x', '-f', '-d')
        repo.heads['master'].checkout()
        return r

    def addPatchset(self, files=[], large=False):
        self.latest_patchset += 1
        if files:
            fn = files[0]
        else:
            fn = '%s-%s' % (self.branch, self.number)
        msg = self.subject + '-' + str(self.latest_patchset)
        c = self.add_fake_change_to_repo(msg, fn, large)
        ps_files = [{'file': '/COMMIT_MSG',
                     'type': 'ADDED'},
                    {'file': 'README',
                     'type': 'MODIFIED'}]
        for f in files:
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
                 "reason": ""}
        return event

    def addApproval(self, category, value, username='jenkins',
                    granted_on=None):
        if not granted_on:
            granted_on = time.time()
        approval = {'description': self.categories[category][0],
                    'type': category,
                    'value': str(value),
                    'by': {
                        'username': username,
                        'email': username + '@example.com',
                    },
                    'grantedOn': int(granted_on)}
        for i, x in enumerate(self.patchsets[-1]['approvals'][:]):
            if x['by']['username'] == username and x['type'] == category:
                del self.patchsets[-1]['approvals'][i]
        self.patchsets[-1]['approvals'].append(approval)
        event = {'approvals': [approval],
                 'author': {'email': 'user@example.com',
                            'name': 'User Name',
                            'username': 'username'},
                 'change': {'branch': self.branch,
                            'id': 'Iaa69c46accf97d0598111724a38250ae76a22c87',
                            'number': str(self.number),
                            'owner': {'email': 'user@example.com',
                                      'name': 'User Name',
                                      'username': 'username'},
                            'project': self.project,
                            'subject': self.subject,
                            'topic': 'master',
                            'url': 'https://hostname/459'},
                 'comment': '',
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


class FakeGerrit(object):
    def __init__(self, *args, **kw):
        self.event_queue = Queue.Queue()
        self.fixture_dir = os.path.join(FIXTURE_DIR, 'gerrit')
        self.change_number = 0
        self.changes = {}

    def addFakeChange(self, project, branch, subject):
        self.change_number += 1
        c = FakeChange(self, self.change_number, project, branch, subject,
                       upstream_root=self.upstream_root)
        self.changes[self.change_number] = c
        return c

    def addEvent(self, data):
        return self.event_queue.put(data)

    def getEvent(self):
        return self.event_queue.get()

    def eventDone(self):
        self.event_queue.task_done()

    def review(self, project, changeid, message, action):
        number, ps = changeid.split(',')
        change = self.changes[int(number)]
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

    def startWatching(self, *args, **kw):
        pass


class BuildHistory(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):
        return ("<Completed build, result: %s name: %s #%s changes: %s>" %
                (self.result, self.name, self.number, self.changes))


class FakeURLOpener(object):
    def __init__(self, upstream_root, fake_gerrit, url):
        self.upstream_root = upstream_root
        self.fake_gerrit = fake_gerrit
        self.url = url

    def read(self):
        res = urlparse.urlparse(self.url)
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


class FakeGerritTrigger(zuul.trigger.gerrit.Gerrit):
    name = 'gerrit'

    def __init__(self, upstream_root, *args):
        super(FakeGerritTrigger, self).__init__(*args)
        self.upstream_root = upstream_root

    def getGitUrl(self, project):
        return os.path.join(self.upstream_root, project.name)


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


class FakeBuild(threading.Thread):
    log = logging.getLogger("zuul.test")

    def __init__(self, worker, job, number, node):
        threading.Thread.__init__(self)
        self.daemon = True
        self.worker = worker
        self.job = job
        self.name = job.name.split(':')[1]
        self.number = number
        self.node = node
        self.parameters = json.loads(job.arguments)
        self.unique = self.parameters['ZUUL_UUID']
        self.wait_condition = threading.Condition()
        self.waiting = False
        self.aborted = False
        self.created = time.time()
        self.description = ''
        self.run_error = False

    def release(self):
        self.wait_condition.acquire()
        self.wait_condition.notify()
        self.waiting = False
        self.log.debug("Build %s released" % self.unique)
        self.wait_condition.release()

    def isWaiting(self):
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
        data = {
            'url': 'https://server/job/%s/%s/' % (self.name, self.number),
            'name': self.name,
            'number': self.number,
            'manager': self.worker.worker_id,
            'worker_name': 'My Worker',
            'worker_hostname': 'localhost',
            'worker_ips': ['127.0.0.1', '192.168.1.1'],
            'worker_fqdn': 'zuul.example.org',
            'worker_program': 'FakeBuilder',
            'worker_version': 'v1.1',
            'worker_extra': {'something': 'else'}
        }

        self.log.debug('Running build %s' % self.unique)

        self.job.sendWorkData(json.dumps(data))
        self.log.debug('Sent WorkData packet with %s' % json.dumps(data))
        self.job.sendWorkStatus(0, 100)

        if self.worker.hold_jobs_in_build:
            self.log.debug('Holding build %s' % self.unique)
            self._wait()
        self.log.debug("Build %s continuing" % self.unique)

        self.worker.lock.acquire()

        result = 'SUCCESS'
        if (('ZUUL_REF' in self.parameters) and
            self.worker.shouldFailTest(self.name,
                                       self.parameters['ZUUL_REF'])):
            result = 'FAILURE'
        if self.aborted:
            result = 'ABORTED'

        if self.run_error:
            work_fail = True
            result = 'RUN_ERROR'
        else:
            data['result'] = result
            work_fail = False

        changes = None
        if 'ZUUL_CHANGE_IDS' in self.parameters:
            changes = self.parameters['ZUUL_CHANGE_IDS']

        self.worker.build_history.append(
            BuildHistory(name=self.name, number=self.number,
                         result=result, changes=changes, node=self.node,
                         uuid=self.unique, description=self.description,
                         pipeline=self.parameters['ZUUL_PIPELINE'])
        )

        self.job.sendWorkData(json.dumps(data))
        if work_fail:
            self.job.sendWorkFail()
        else:
            self.job.sendWorkComplete(json.dumps(data))
        del self.worker.gearman_jobs[self.job.unique]
        self.worker.running_builds.remove(self)
        self.worker.lock.release()


class FakeWorker(gear.Worker):
    def __init__(self, worker_id, test):
        super(FakeWorker, self).__init__(worker_id)
        self.gearman_jobs = {}
        self.build_history = []
        self.running_builds = []
        self.build_counter = 0
        self.fail_tests = {}
        self.test = test

        self.hold_jobs_in_build = False
        self.lock = threading.Lock()
        self.__work_thread = threading.Thread(target=self.work)
        self.__work_thread.daemon = True
        self.__work_thread.start()

    def handleJob(self, job):
        parts = job.name.split(":")
        cmd = parts[0]
        name = parts[1]
        if len(parts) > 2:
            node = parts[2]
        else:
            node = None
        if cmd == 'build':
            self.handleBuild(job, name, node)
        elif cmd == 'stop':
            self.handleStop(job, name)
        elif cmd == 'set_description':
            self.handleSetDescription(job, name)

    def handleBuild(self, job, name, node):
        build = FakeBuild(self, job, self.build_counter, node)
        job.build = build
        self.gearman_jobs[job.unique] = job
        self.build_counter += 1

        self.running_builds.append(build)
        build.start()

    def handleStop(self, job, name):
        self.log.debug("handle stop")
        parameters = json.loads(job.arguments)
        name = parameters['name']
        number = parameters['number']
        for build in self.running_builds:
            if build.name == name and build.number == number:
                build.aborted = True
                build.release()
                job.sendWorkComplete()
                return
        job.sendWorkFail()

    def handleSetDescription(self, job, name):
        self.log.debug("handle set description")
        parameters = json.loads(job.arguments)
        name = parameters['name']
        number = parameters['number']
        descr = parameters['html_description']
        for build in self.running_builds:
            if build.name == name and build.number == number:
                build.description = descr
                job.sendWorkComplete()
                return
        for build in self.build_history:
            if build.name == name and build.number == number:
                build.description = descr
                job.sendWorkComplete()
                return
        job.sendWorkFail()

    def work(self):
        while self.running:
            try:
                job = self.getJob()
            except gear.InterruptedError:
                continue
            try:
                self.handleJob(job)
            except:
                self.log.exception("Worker exception:")

    def addFailTest(self, name, change):
        l = self.fail_tests.get(name, [])
        l.append(change)
        self.fail_tests[name] = l

    def shouldFailTest(self, name, ref):
        l = self.fail_tests.get(name, [])
        for change in l:
            if self.test.ref_has_change(ref, change):
                return True
        return False

    def release(self, regex=None):
        builds = self.running_builds[:]
        self.log.debug("releasing build %s (%s)" % (regex,
                                                    len(self.running_builds)))
        for build in builds:
            if not regex or re.match(regex, build.name):
                self.log.debug("releasing build %s" %
                               (build.parameters['ZUUL_UUID']))
                build.release()
            else:
                self.log.debug("not releasing build %s" %
                               (build.parameters['ZUUL_UUID']))
        self.log.debug("done releasing builds %s (%s)" %
                       (regex, len(self.running_builds)))


class FakeGearmanServer(gear.Server):
    def __init__(self):
        self.hold_jobs_in_queue = False
        super(FakeGearmanServer, self).__init__(0)

    def getJobForConnection(self, connection, peek=False):
        for queue in [self.high_queue, self.normal_queue, self.low_queue]:
            for job in queue:
                if not hasattr(job, 'waiting'):
                    if job.name.startswith('build:'):
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
        released = False
        qlen = (len(self.high_queue) + len(self.normal_queue) +
                len(self.low_queue))
        self.log.debug("releasing queued job %s (%s)" % (regex, qlen))
        for job in self.getQueue():
            cmd, name = job.name.split(':')
            if cmd != 'build':
                continue
            if not regex or re.match(regex, name):
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


class TestScheduler(testtools.TestCase):
    log = logging.getLogger("zuul.test")

    def setUp(self):
        super(TestScheduler, self).setUp()
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
        tmp_root = self.useFixture(fixtures.TempDir(
            rootdir=os.environ.get("ZUUL_TEST_ROOT"))).path
        self.test_root = os.path.join(tmp_root, "zuul-test")
        self.upstream_root = os.path.join(self.test_root, "upstream")
        self.git_root = os.path.join(self.test_root, "git")

        CONFIG.set('merger', 'git_dir', self.git_root)
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)
        os.makedirs(self.test_root)
        os.makedirs(self.upstream_root)
        os.makedirs(self.git_root)

        # For each project in config:
        self.init_repo("org/project")
        self.init_repo("org/project1")
        self.init_repo("org/project2")
        self.init_repo("org/project3")
        self.init_repo("org/one-job-project")
        self.init_repo("org/nonvoting-project")
        self.init_repo("org/templated-project")
        self.init_repo("org/layered-project")
        self.init_repo("org/node-project")
        self.init_repo("org/conflict-project")
        self.init_repo("org/noop-project")

        self.statsd = FakeStatsd()
        os.environ['STATSD_HOST'] = 'localhost'
        os.environ['STATSD_PORT'] = str(self.statsd.port)
        self.statsd.start()
        # the statsd client object is configured in the statsd module import
        reload(statsd)
        reload(zuul.scheduler)

        self.gearman_server = FakeGearmanServer()

        self.config = ConfigParser.ConfigParser()
        cfg = StringIO()
        CONFIG.write(cfg)
        cfg.seek(0)
        self.config.readfp(cfg)
        self.config.set('gearman', 'port', str(self.gearman_server.port))

        self.worker = FakeWorker('fake_worker', self)
        self.worker.addServer('127.0.0.1', self.gearman_server.port)
        self.gearman_server.worker = self.worker

        self.merge_server = zuul.merger.server.MergeServer(self.config)
        self.merge_server.start()

        self.sched = zuul.scheduler.Scheduler()

        self.useFixture(fixtures.MonkeyPatch('swiftclient.client.Connection',
                                             FakeSwiftClientConnection))
        self.swift = zuul.lib.swift.Swift(self.config)

        def URLOpenerFactory(*args, **kw):
            if isinstance(args[0], urllib2.Request):
                return old_urlopen(*args, **kw)
            args = [self.fake_gerrit] + list(args)
            return FakeURLOpener(self.upstream_root, *args, **kw)

        old_urlopen = urllib2.urlopen
        urllib2.urlopen = URLOpenerFactory

        self.launcher = zuul.launcher.gearman.Gearman(self.config, self.sched,
                                                      self.swift)
        self.merge_client = zuul.merger.client.MergeClient(
            self.config, self.sched)

        self.smtp_messages = []

        def FakeSMTPFactory(*args, **kw):
            args = [self.smtp_messages] + list(args)
            return FakeSMTP(*args, **kw)

        zuul.lib.gerrit.Gerrit = FakeGerrit
        self.useFixture(fixtures.MonkeyPatch('smtplib.SMTP', FakeSMTPFactory))

        self.gerrit = FakeGerritTrigger(
            self.upstream_root, self.config, self.sched)
        self.gerrit.replication_timeout = 1.5
        self.gerrit.replication_retry_interval = 0.5
        self.fake_gerrit = self.gerrit.gerrit
        self.fake_gerrit.upstream_root = self.upstream_root

        self.webapp = zuul.webapp.WebApp(self.sched, port=0)
        self.rpc = zuul.rpclistener.RPCListener(self.config, self.sched)

        self.sched.setLauncher(self.launcher)
        self.sched.setMerger(self.merge_client)
        self.sched.registerTrigger(self.gerrit)
        self.timer = zuul.trigger.timer.Timer(self.config, self.sched)
        self.sched.registerTrigger(self.timer)

        self.sched.registerReporter(
            zuul.reporter.gerrit.Reporter(self.gerrit))
        self.smtp_reporter = zuul.reporter.smtp.Reporter(
            self.config.get('smtp', 'default_from'),
            self.config.get('smtp', 'default_to'),
            self.config.get('smtp', 'server'))
        self.sched.registerReporter(self.smtp_reporter)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()
        self.webapp.start()
        self.rpc.start()
        self.launcher.gearman.waitForServer()
        self.registerJobs()
        self.builds = self.worker.running_builds
        self.history = self.worker.build_history

        self.addCleanup(self.assertFinalState)
        self.addCleanup(self.shutdown)

    def assertFinalState(self):
        # Make sure that the change cache is cleared
        self.assertEqual(len(self.gerrit._change_cache.keys()), 0)
        # Make sure that git.Repo objects have been garbage collected.
        repos = []
        gc.collect()
        for obj in gc.get_objects():
            if isinstance(obj, git.Repo):
                repos.append(obj)
        self.assertEqual(len(repos), 0)
        self.assertEmptyQueues()

    def shutdown(self):
        self.log.debug("Shutting down after tests")
        self.launcher.stop()
        self.merge_server.stop()
        self.merge_server.join()
        self.merge_client.stop()
        self.worker.shutdown()
        self.gerrit.stop()
        self.timer.stop()
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
        super(TestScheduler, self).tearDown()

    def init_repo(self, project):
        parts = project.split('/')
        path = os.path.join(self.upstream_root, *parts[:-1])
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(self.upstream_root, project)
        repo = git.Repo.init(path)

        repo.config_writer().set_value('user', 'email', 'user@example.com')
        repo.config_writer().set_value('user', 'name', 'User Name')
        repo.config_writer().write()

        fn = os.path.join(path, 'README')
        f = open(fn, 'w')
        f.write("test\n")
        f.close()
        repo.index.add([fn])
        repo.index.commit('initial commit')
        master = repo.create_head('master')
        repo.create_tag('init')

        mp = repo.create_head('mp')
        repo.head.reference = mp
        f = open(fn, 'a')
        f.write("test mp\n")
        f.close()
        repo.index.add([fn])
        repo.index.commit('mp commit')

        repo.head.reference = master
        repo.head.reset(index=True, working_tree=True)
        repo.git.clean('-x', '-f', '-d')

    def ref_has_change(self, ref, change):
        path = os.path.join(self.git_root, change.project)
        repo = git.Repo(path)
        for commit in repo.iter_commits(ref):
            if commit.message.strip() == ('%s-1' % change.subject):
                return True
        return False

    def job_has_changes(self, *args):
        job = args[0]
        commits = args[1:]
        if isinstance(job, FakeBuild):
            parameters = job.parameters
        else:
            parameters = json.loads(job.arguments)
        project = parameters['ZUUL_PROJECT']
        path = os.path.join(self.git_root, project)
        repo = git.Repo(path)
        ref = parameters['ZUUL_REF']
        sha = parameters['ZUUL_COMMIT']
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref)]
        commit_messages = ['%s-1' % commit.subject for commit in commits]
        self.log.debug("Checking if job %s has changes; commit_messages %s;"
                       " repo_messages %s; sha %s" % (job, commit_messages,
                                                      repo_messages, sha))
        for msg in commit_messages:
            if msg not in repo_messages:
                self.log.debug("  messages do not match")
                return False
        if repo_shas[0] != sha:
            self.log.debug("  sha does not match")
            return False
        self.log.debug("  OK")
        return True

    def registerJobs(self):
        count = 0
        for job in self.sched.layout.jobs.keys():
            self.worker.registerFunction('build:' + job)
            count += 1
        self.worker.registerFunction('stop:' + self.worker.worker_id)
        count += 1

        while len(self.gearman_server.functions) < count:
            time.sleep(0)

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
        self.worker.setFunctions([])
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
        self.merge_server.register()

    def haveAllBuildsReported(self):
        # See if Zuul is waiting on a meta job to complete
        if self.launcher.meta_jobs:
            return False
        # Find out if every build that the worker has completed has been
        # reported back to Zuul.  If it hasn't then that means a Gearman
        # event is still in transit and the system is not stable.
        for build in self.worker.build_history:
            zbuild = self.launcher.builds.get(build.uuid)
            if not zbuild:
                # It has already been reported
                continue
            # It hasn't been reported yet.
            return False
        # Make sure that none of the worker connections are in GRAB_WAIT
        for connection in self.worker.active_connections:
            if connection.state == 'GRAB_WAIT':
                return False
        return True

    def areAllBuildsWaiting(self):
        ret = True

        builds = self.launcher.builds.values()
        for build in builds:
            client_job = None
            for conn in self.launcher.gearman.active_connections:
                for j in conn.related_jobs.values():
                    if j.unique == build.uuid:
                        client_job = j
                        break
            if not client_job:
                self.log.debug("%s is not known to the gearman client" %
                               build)
                ret = False
                continue
            if not client_job.handle:
                self.log.debug("%s has no handle" % client_job)
                ret = False
                continue
            server_job = self.gearman_server.jobs.get(client_job.handle)
            if not server_job:
                self.log.debug("%s is not known to the gearman server" %
                               client_job)
                ret = False
                continue
            if not hasattr(server_job, 'waiting'):
                self.log.debug("%s is being enqueued" % server_job)
                ret = False
                continue
            if server_job.waiting:
                continue
            worker_job = self.worker.gearman_jobs.get(server_job.unique)
            if worker_job:
                if worker_job.build.isWaiting():
                    continue
                else:
                    self.log.debug("%s is running" % worker_job)
                    ret = False
            else:
                self.log.debug("%s is unassigned" % server_job)
                ret = False
        return ret

    def waitUntilSettled(self):
        self.log.debug("Waiting until settled...")
        start = time.time()
        while True:
            if time.time() - start > 10:
                print 'queue status:',
                print self.sched.trigger_event_queue.empty(),
                print self.sched.result_event_queue.empty(),
                print self.fake_gerrit.event_queue.empty(),
                print self.areAllBuildsWaiting()
                raise Exception("Timeout waiting for Zuul to settle")
            # Make sure no new events show up while we're checking
            self.worker.lock.acquire()
            # have all build states propogated to zuul?
            if self.haveAllBuildsReported():
                # Join ensures that the queue is empty _and_ events have been
                # processed
                self.fake_gerrit.event_queue.join()
                self.sched.trigger_event_queue.join()
                self.sched.result_event_queue.join()
                self.sched.run_handler_lock.acquire()
                if (self.sched.trigger_event_queue.empty() and
                    self.sched.result_event_queue.empty() and
                    self.fake_gerrit.event_queue.empty() and
                    not self.merge_client.build_sets and
                    self.haveAllBuildsReported() and
                    self.areAllBuildsWaiting()):
                    self.sched.run_handler_lock.release()
                    self.worker.lock.release()
                    self.log.debug("...settled.")
                    return
                self.sched.run_handler_lock.release()
            self.worker.lock.release()
            self.sched.wake_event.wait(0.1)

    def countJobResults(self, jobs, result):
        jobs = filter(lambda x: x.result == result, jobs)
        return len(jobs)

    def getJobFromHistory(self, name):
        history = self.worker.build_history
        for job in history:
            if job.name == name:
                return job
        raise Exception("Unable to find job %s in history" % name)

    def assertEmptyQueues(self):
        # Make sure there are no orphaned jobs
        for pipeline in self.sched.layout.pipelines.values():
            for queue in pipeline.queues:
                if len(queue.queue) != 0:
                    print 'pipeline %s queue %s contents %s' % (
                        pipeline.name, queue.name, queue.queue)
                self.assertEqual(len(queue.queue), 0)

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

    def test_jobs_launched(self):
        "Test that jobs are launched and a change is merged"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

        self.assertReportedStat('gerrit.event.comment-added', value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.current_changes',
                                value='1|g')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.resident_time', kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.total_changes',
                                value='1|c')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.resident_time', kind='ms')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.total_changes', value='1|c')

    def test_initial_pipeline_gauges(self):
        "Test that each pipeline reported its length on start"
        pipeline_names = self.sched.layout.pipelines.keys()
        self.assertNotEqual(len(pipeline_names), 0)
        for name in pipeline_names:
            self.assertReportedStat('zuul.pipeline.%s.current_changes' % name,
                                    value='0|g')

    def test_duplicate_pipelines(self):
        "Test that a change matching multiple pipelines works"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getChangeRestoredEvent())
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)
        self.history[0].name == 'project-test1'
        self.history[1].name == 'project-test1'

        self.assertEqual(len(A.messages), 2)
        if 'dup1/project-test1' in A.messages[0]:
            self.assertIn('dup1/project-test1', A.messages[0])
            self.assertNotIn('dup2/project-test1', A.messages[0])
            self.assertNotIn('dup1/project-test1', A.messages[1])
            self.assertIn('dup2/project-test1', A.messages[1])
        else:
            self.assertIn('dup1/project-test1', A.messages[1])
            self.assertNotIn('dup2/project-test1', A.messages[1])
            self.assertNotIn('dup1/project-test1', A.messages[0])
            self.assertIn('dup2/project-test1', A.messages[0])

    def test_parallel_changes(self):
        "Test that changes are tested in parallel and merged in series"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))
        self.assertEqual(self.builds[2].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[3], A, B))

        self.assertEqual(self.builds[4].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[4], A, B, C))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[1], A))

        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[2], A, B))
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[3], A, B))

        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertTrue(self.job_has_changes(self.builds[4], A, B, C))
        self.assertEqual(self.builds[5].name, 'project-test2')
        self.assertTrue(self.job_has_changes(self.builds[5], A, B, C))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(len(self.history), 9)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_changes(self):
        "Test that a change behind a failed change is retested"
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()

        self.waitUntilSettled()
        # It's certain that the merge job for change 2 will run, but
        # the test1 and test2 jobs may or may not run.
        self.assertTrue(len(self.history) > 6)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)

    def test_independent_queues(self):
        "Test that changes end up in the right queues"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        # There should be one merge job at the head of each queue running
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertEqual(self.builds[1].name, 'project1-merge')
        self.assertTrue(self.job_has_changes(self.builds[1], B))

        # Release the current merge builds
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        # Release the merge job for project2 which is behind project1
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # All the test builds should be running:
        # project1 (3) + project2 (3) + project (2) = 8
        self.assertEqual(len(self.builds), 8)

        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)

        self.assertEqual(len(self.history), 11)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_at_head(self):
        "Test that if a change at the head fails, jobs behind it are canceled"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.release(self.builds[0])
        self.waitUntilSettled()

        # project-test2, project-merge for B
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 4)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 15)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_in_middle(self):
        "Test a failed change in the middle of the queue"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.release(self.builds[2])
        self.waitUntilSettled()

        # project-test1 and project-test2 for A
        # project-test2 for B
        # project-merge for C (without B)
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 2)

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # project-test1 and project-test2 for A
        # project-test2 for B
        # project-test1 and project-test2 for C
        self.assertEqual(len(self.builds), 5)

        items = self.sched.layout.pipelines['gate'].getAllItems()
        builds = items[0].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, None), 2)
        builds = items[1].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, 'FAILURE'), 1)
        self.assertEqual(self.countJobResults(builds, None), 1)
        builds = items[2].current_build_set.getBuilds()
        self.assertEqual(self.countJobResults(builds, 'SUCCESS'), 1)
        self.assertEqual(self.countJobResults(builds, None), 2)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 12)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_failed_change_at_head_with_queue(self):
        "Test that if a change at the head fails, queued jobs are canceled"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].name, 'build:project-merge')
        self.assertTrue(self.job_has_changes(queue[0], A))

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(queue), 6)
        self.assertEqual(queue[0].name, 'build:project-test1')
        self.assertEqual(queue[1].name, 'build:project-test2')
        self.assertEqual(queue[2].name, 'build:project-test1')
        self.assertEqual(queue[3].name, 'build:project-test2')
        self.assertEqual(queue[4].name, 'build:project-test1')
        self.assertEqual(queue[5].name, 'build:project-test2')

        self.release(queue[0])
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        queue = self.gearman_server.getQueue()
        self.assertEqual(len(queue), 2)  # project-test2, project-merge for B
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 0)

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 11)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_two_failed_changes_at_head(self):
        "Test that changes are reparented correctly if 2 fail at head"

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project-test1', A)
        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], A))
        self.assertTrue(self.job_has_changes(self.builds[2], A))
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[4], A))
        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))

        # Fail change B first
        self.release(self.builds[2])
        self.waitUntilSettled()

        # restart of C after B failure
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 5)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test2')
        self.assertEqual(self.builds[3].name, 'project-test1')
        self.assertEqual(self.builds[4].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[1], A))
        self.assertTrue(self.job_has_changes(self.builds[2], A))
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[4], A))
        self.assertFalse(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))

        # Finish running all passing jobs for change A
        self.release(self.builds[1])
        self.waitUntilSettled()
        # Fail and report change A
        self.release(self.builds[0])
        self.waitUntilSettled()

        # restart of B,C after A failure
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')  # B
        self.assertEqual(self.builds[1].name, 'project-test2')  # B
        self.assertEqual(self.builds[2].name, 'project-test1')  # C
        self.assertEqual(self.builds[3].name, 'project-test2')  # C

        self.assertFalse(self.job_has_changes(self.builds[1], A))
        self.assertTrue(self.job_has_changes(self.builds[1], B))
        self.assertFalse(self.job_has_changes(self.builds[1], C))

        self.assertFalse(self.job_has_changes(self.builds[2], A))
        # After A failed and B and C restarted, B should be back in
        # C's tests because it has not failed yet.
        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 21)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_patch_order(self):
        "Test that dependent patches are tested in the right order"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        M2 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M2')
        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M2.setMerged()
        M1.setMerged()

        # C -> B -> A -> M1 -> M2
        # M2 is here to make sure it is never queried.  If it is, it
        # means zuul is walking down the entire history of merged
        # changes.

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)
        M1.setDependsOn(M2, 1)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'NEW')

        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.assertEqual(M2.queried, 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_trigger_cache(self):
        "Test that the trigger cache operates correctly"
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        X = self.fake_gerrit.addFakeChange('org/project', 'master', 'X')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(X.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        for build in self.builds:
            if build.parameters['ZUUL_PIPELINE'] == 'check':
                build.release()
        self.waitUntilSettled()
        for build in self.builds:
            if build.parameters['ZUUL_PIPELINE'] == 'check':
                build.release()
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.log.debug("len %s " % self.gerrit._change_cache.keys())
        # there should still be changes in the cache
        self.assertNotEqual(len(self.gerrit._change_cache.keys()), 0)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(A.queried, 2)  # Initial and isMerged
        self.assertEqual(B.queried, 3)  # Initial A, refresh from B, isMerged

    def test_can_merge(self):
        "Test whether a change is ready to merge"
        # TODO: move to test_gerrit (this is a unit test!)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        trigger = self.sched.layout.pipelines['gate'].trigger
        a = self.sched.triggers['gerrit'].getChange(1, 2)
        mgr = self.sched.layout.pipelines['gate'].manager
        self.assertFalse(trigger.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('CRVW', 2)
        a = trigger.getChange(1, 2, refresh=True)
        self.assertFalse(trigger.canMerge(a, mgr.getSubmitAllowNeeds()))

        A.addApproval('APRV', 1)
        a = trigger.getChange(1, 2, refresh=True)
        self.assertTrue(trigger.canMerge(a, mgr.getSubmitAllowNeeds()))
        trigger.maintainCache([])

    def test_build_configuration(self):
        "Test that zuul merges the right commits for testing"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'B-1', 'C-1']
        self.assertEqual(repo_messages, correct_messages)

    def test_build_configuration_conflict(self):
        "Test that merge conflicts are handled"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'A')
        A.addPatchset(['conflict'])
        B = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'B')
        B.addPatchset(['conflict'])
        C = self.fake_gerrit.addFakeChange('org/conflict-project',
                                           'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.reported, 1)
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.reported, 1)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 2)  # A and C merge jobs

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 6)

    def test_post(self):
        "Test that post jobs run"

        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "d479a0bfcb34da57a31adb2a595c0cf687812543",
                "refName": "master",
                "project": "org/project",
            }
        }
        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        job_names = [x.name for x in self.history]
        self.assertEqual(len(self.history), 1)
        self.assertIn('project-post', job_names)

    def test_build_configuration_branch(self):
        "Test that the right commits are on alternate branches"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'mp', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'mp', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'A-1', 'B-1', 'C-1']
        self.assertEqual(repo_messages, correct_messages)

    def test_build_configuration_branch_interaction(self):
        "Test that switching between branches works"
        self.test_build_configuration()
        self.test_build_configuration_branch()
        # C has been merged, undo that
        path = os.path.join(self.upstream_root, "org/project")
        repo = git.Repo(path)
        repo.heads.master.commit = repo.commit('init')
        self.test_build_configuration()

    def test_build_configuration_multi_branch(self):
        "Test that dependent changes on multiple branches are merged"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'mp', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        job_A = None
        for job in queue:
            if 'project-merge' in job.name:
                job_A = job
        ref_A = self.getParameter(job_A, 'ZUUL_REF')
        commit_A = self.getParameter(job_A, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change A: %s" % ref_A)
        self.log.debug("Got Zuul commit for change A: %s" % commit_A)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        job_B = None
        for job in queue:
            if 'project-merge' in job.name:
                job_B = job
        ref_B = self.getParameter(job_B, 'ZUUL_REF')
        commit_B = self.getParameter(job_B, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change B: %s" % ref_B)
        self.log.debug("Got Zuul commit for change B: %s" % commit_B)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        for job in queue:
            if 'project-merge' in job.name:
                job_C = job
        ref_C = self.getParameter(job_C, 'ZUUL_REF')
        commit_C = self.getParameter(job_C, 'ZUUL_COMMIT')
        self.log.debug("Got Zuul ref for change C: %s" % ref_C)
        self.log.debug("Got Zuul commit for change C: %s" % commit_C)
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_C)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_C)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'C-1']
        # Ensure the right commits are in the history for this ref
        self.assertEqual(repo_messages, correct_messages)
        # Ensure ZUUL_REF -> ZUUL_COMMIT
        self.assertEqual(repo_shas[0], commit_C)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_B)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_B)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'B-1']
        self.assertEqual(repo_messages, correct_messages)
        self.assertEqual(repo_shas[0], commit_B)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_A)]
        repo_shas = [c.hexsha for c in repo.iter_commits(ref_A)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1']
        self.assertEqual(repo_messages, correct_messages)
        self.assertEqual(repo_shas[0], commit_A)

        self.assertNotEqual(ref_A, ref_B, ref_C)
        self.assertNotEqual(commit_A, commit_B, commit_C)

    def test_one_job_project(self):
        "Test that queueing works with one job"
        A = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/one-job-project',
                                           'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_job_from_templates_launched(self):
        "Test whether a job generated via a template can be launched"

        A = self.fake_gerrit.addFakeChange(
            'org/templated-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

    def test_layered_templates(self):
        "Test whether a job generated via a template can be launched"

        A = self.fake_gerrit.addFakeChange(
            'org/layered-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-test3'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-test4'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('layered-project-foo-test5'
                                                ).result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test6').result,
                         'SUCCESS')

    def test_dependent_changes_dequeue(self):
        "Test that dependent patches are not needlessly tested"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        M1 = self.fake_gerrit.addFakeChange('org/project', 'master', 'M1')
        M1.setMerged()

        # C -> B -> A -> M1

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M1, 1)

        self.worker.addFailTest('project-merge', A)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 1)

    def test_failing_dependent_changes(self):
        "Test that failing dependent patches are taken out of stream"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project', 'master', 'E')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)

        # E, D -> C -> B, A

        D.setDependsOn(C, 1)
        C.setDependsOn(B, 1)

        self.worker.addFailTest('project-test1', B)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        for build in self.builds:
            if build.parameters['ZUUL_CHANGE'] != '1':
                build.release()
                self.waitUntilSettled()

        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'NEW')
        self.assertEqual(D.reported, 2)
        self.assertEqual(E.data['status'], 'MERGED')
        self.assertEqual(E.reported, 2)
        self.assertEqual(len(self.history), 18)

    def test_head_is_dequeued_once(self):
        "Test that if a change at the head fails it is dequeued only once"
        # If it's dequeued more than once, we should see extra
        # aborted jobs.

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.worker.addFailTest('project1-test1', A)
        self.worker.addFailTest('project1-test2', A)
        self.worker.addFailTest('project1-project2-integration', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project1-merge')
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 9)
        self.assertEqual(self.builds[0].name, 'project1-test1')
        self.assertEqual(self.builds[1].name, 'project1-test2')
        self.assertEqual(self.builds[2].name, 'project1-project2-integration')
        self.assertEqual(self.builds[3].name, 'project1-test1')
        self.assertEqual(self.builds[4].name, 'project1-test2')
        self.assertEqual(self.builds[5].name, 'project1-project2-integration')
        self.assertEqual(self.builds[6].name, 'project1-test1')
        self.assertEqual(self.builds[7].name, 'project1-test2')
        self.assertEqual(self.builds[8].name, 'project1-project2-integration')

        self.release(self.builds[0])
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 3)  # test2,integration, merge for B
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 6)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 20)

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)

    def test_nonvoting_job(self):
        "Test that non-voting jobs don't vote."

        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('nonvoting-project-test2', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-merge').result,
            'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test1').result,
            'SUCCESS')
        self.assertEqual(
            self.getJobFromHistory('nonvoting-project-test2').result,
            'FAILURE')

    def test_check_queue_success(self):
        "Test successful check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')

    def test_check_queue_failure(self):
        "Test failed check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.worker.addFailTest('project-test2', A)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'FAILURE')

    def test_dependent_behind_dequeue(self):
        "test that dependent changes behind dequeued changes work"
        # This complicated test is a reproduction of a real life bug
        self.sched.reconfigure(self.config)

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        E = self.fake_gerrit.addFakeChange('org/project2', 'master', 'E')
        F = self.fake_gerrit.addFakeChange('org/project3', 'master', 'F')
        D.setDependsOn(C, 1)
        E.setDependsOn(D, 1)
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        E.addApproval('CRVW', 2)
        F.addApproval('CRVW', 2)

        A.fail_merge = True

        # Change object re-use in the gerrit trigger is hidden if
        # changes are added in quick succession; waiting makes it more
        # like real life.
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(F.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # all jobs running

        # Grab pointers to the jobs we want to release before
        # releasing any, because list indexes may change as
        # the jobs complete.
        a, b, c = self.builds[:3]
        a.release()
        b.release()
        c.release()
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(E.data['status'], 'MERGED')
        self.assertEqual(F.data['status'], 'MERGED')

        self.assertEqual(A.reported, 2)
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.reported, 2)
        self.assertEqual(E.reported, 2)
        self.assertEqual(F.reported, 2)

        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 15)
        self.assertEqual(len(self.history), 44)

    def test_merger_repack(self):
        "Test that the merger works after a repack"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEmptyQueues()
        self.worker.build_history = []

        path = os.path.join(self.git_root, "org/project")
        print repack_repo(path)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_merger_repack_large_change(self):
        "Test that the merger works with large changes after a repack"
        # https://bugs.launchpad.net/zuul/+bug/1078946
        # This test assumes the repo is already cloned; make sure it is
        url = self.sched.triggers['gerrit'].getGitUrl(
            self.sched.layout.projects['org/project1'])
        self.merge_server.merger.addProject('org/project1', url)
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addPatchset(large=True)
        path = os.path.join(self.upstream_root, "org/project1")
        print repack_repo(path)
        path = os.path.join(self.git_root, "org/project1")
        print repack_repo(path)

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project1-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project1-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project1-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_nonexistent_job(self):
        "Test launching a job that doesn't exist"
        # Set to the state immediately after a restart
        self.resetGearmanServer()
        self.launcher.negative_function_cache_ttl = 0

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        # There may be a thread about to report a lost change
        while A.reported < 2:
            self.waitUntilSettled()
        job_names = [x.name for x in self.history]
        self.assertFalse(job_names)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEmptyQueues()

        # Make sure things still work:
        self.registerJobs()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_single_nonexistent_post_job(self):
        "Test launching a single post job that doesn't exist"
        e = {
            "type": "ref-updated",
            "submitter": {
                "name": "User Name",
            },
            "refUpdate": {
                "oldRev": "90f173846e3af9154517b88543ffbd1691f31366",
                "newRev": "d479a0bfcb34da57a31adb2a595c0cf687812543",
                "refName": "master",
                "project": "org/project",
            }
        }
        # Set to the state immediately after a restart
        self.resetGearmanServer()
        self.launcher.negative_function_cache_ttl = 0

        self.fake_gerrit.addEvent(e)
        self.waitUntilSettled()

        self.assertEqual(len(self.history), 0)

    def test_new_patchset_dequeues_old(self):
        "Test that a new patchset causes the old to be dequeued"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.worker.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)
        self.assertEqual(len(self.history), 9)  # 3 each for A, B, D.

    def test_zuul_url_return(self):
        "Test if ZUUL_URL is returning when zuul_url is set in zuul.conf"
        self.assertTrue(self.sched.config.has_option('merger', 'zuul_url'))
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 1)
        for build in self.builds:
            self.assertTrue('ZUUL_URL' in build.parameters)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_new_patchset_dequeues_old_on_head(self):
        "Test that a new patchset causes the old to be dequeued (at head)"
        # D -> C (depends on B) -> B (depends on A) -> A -> M
        self.worker.hold_jobs_in_build = True
        M = self.fake_gerrit.addFakeChange('org/project', 'master', 'M')
        M.setMerged()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)

        C.setDependsOn(B, 1)
        B.setDependsOn(A, 1)
        A.setDependsOn(M, 1)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()

        A.addPatchset()
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)
        self.assertEqual(len(self.history), 7)

    def test_new_patchset_dequeues_old_without_dependents(self):
        "Test that a new patchset causes only the old to be dequeued"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)
        self.assertEqual(len(self.history), 9)

    def test_new_patchset_dequeues_old_independent_queue(self):
        "Test that a new patchset causes the old to be dequeued (independent)"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.fake_gerrit.addEvent(C.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        B.addPatchset()
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(2))
        self.waitUntilSettled()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(A.reported, 1)
        self.assertEqual(B.data['status'], 'NEW')
        self.assertEqual(B.reported, 1)
        self.assertEqual(C.data['status'], 'NEW')
        self.assertEqual(C.reported, 1)
        self.assertEqual(len(self.history), 10)
        self.assertEqual(self.countJobResults(self.history, 'ABORTED'), 1)

    def test_noop_job(self):
        "Test that the internal noop job works"
        A = self.fake_gerrit.addFakeChange('org/noop-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())
        self.assertEqual(len(self.history), 0)
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_zuul_refs(self):
        "Test that zuul refs exist and have the right changes"
        self.worker.hold_jobs_in_build = True
        M1 = self.fake_gerrit.addFakeChange('org/project1', 'master', 'M1')
        M1.setMerged()
        M2 = self.fake_gerrit.addFakeChange('org/project2', 'master', 'M2')
        M2.setMerged()

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        D = self.fake_gerrit.addFakeChange('org/project2', 'master', 'D')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        D.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        a_zref = b_zref = c_zref = d_zref = None
        for x in self.builds:
            if x.parameters['ZUUL_CHANGE'] == '3':
                a_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '4':
                b_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '5':
                c_zref = x.parameters['ZUUL_REF']
            if x.parameters['ZUUL_CHANGE'] == '6':
                d_zref = x.parameters['ZUUL_REF']

        # There are... four... refs.
        self.assertIsNotNone(a_zref)
        self.assertIsNotNone(b_zref)
        self.assertIsNotNone(c_zref)
        self.assertIsNotNone(d_zref)

        # And they should all be different
        refs = set([a_zref, b_zref, c_zref, d_zref])
        self.assertEqual(len(refs), 4)

        # a ref should have a, not b, and should not be in project2
        self.assertTrue(self.ref_has_change(a_zref, A))
        self.assertFalse(self.ref_has_change(a_zref, B))
        self.assertFalse(self.ref_has_change(a_zref, M2))

        # b ref should have a and b, and should not be in project2
        self.assertTrue(self.ref_has_change(b_zref, A))
        self.assertTrue(self.ref_has_change(b_zref, B))
        self.assertFalse(self.ref_has_change(b_zref, M2))

        # c ref should have a and b in 1, c in 2
        self.assertTrue(self.ref_has_change(c_zref, A))
        self.assertTrue(self.ref_has_change(c_zref, B))
        self.assertTrue(self.ref_has_change(c_zref, C))
        self.assertFalse(self.ref_has_change(c_zref, D))

        # d ref should have a and b in 1, c and d in 2
        self.assertTrue(self.ref_has_change(d_zref, A))
        self.assertTrue(self.ref_has_change(d_zref, B))
        self.assertTrue(self.ref_has_change(d_zref, C))
        self.assertTrue(self.ref_has_change(d_zref, D))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)
        self.assertEqual(D.data['status'], 'MERGED')
        self.assertEqual(D.reported, 2)

    def test_required_approval_check_and_gate(self):
        "Test required-approval triggers both check and gate"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-require-approval.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        # Add a too-old +1
        A.addApproval('VRFY', 1, granted_on=time.time() - 72 * 60 * 60)

        aprv = A.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(aprv)
        self.waitUntilSettled()
        # Should have run a check job
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project-check')

        # Report the result of that check job (overrides previous vrfy)
        # Skynet alert: this should trigger a gate job now that
        # all reqs are met
        self.fake_gerrit.addEvent(A.addApproval('VRFY', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, 'project-gate')

    def test_required_approval_newer(self):
        "Test required-approval newer trigger parameter"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-require-approval.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        aprv = A.addApproval('APRV', 1)
        self.fake_gerrit.addEvent(aprv)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add a too-old +1, should trigger check but not gate
        A.addApproval('VRFY', 1, granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(aprv)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project-check')

        # Add a recent +1
        self.fake_gerrit.addEvent(A.addApproval('VRFY', 1))
        self.fake_gerrit.addEvent(aprv)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 2)
        self.assertEqual(self.history[1].name, 'project-gate')

    def test_required_approval_older(self):
        "Test required-approval older trigger parameter"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-require-approval.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        crvw = A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(crvw)
        self.waitUntilSettled()
        # No +1 from Jenkins so should not be enqueued
        self.assertEqual(len(self.history), 0)

        # Add an old +1 and trigger check with a comment
        A.addApproval('VRFY', 1, granted_on=time.time() - 72 * 60 * 60)
        self.fake_gerrit.addEvent(crvw)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'project-check')

        # Add a recent +1 and make sure nothing changes
        A.addApproval('VRFY', 1)
        self.fake_gerrit.addEvent(crvw)
        self.waitUntilSettled()
        self.assertEqual(len(self.history), 1)

        # The last thing we did was query a change then do nothing
        # with a pipeline, so it will be in the cache; clean it up so
        # it does not fail the test.
        for pipeline in self.sched.layout.pipelines.values():
            pipeline.trigger.maintainCache([])

    def test_rerun_on_error(self):
        "Test that if a worker fails to run a job, it is run again"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.builds[0].run_error = True
        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(self.countJobResults(self.history, 'RUN_ERROR'), 1)
        self.assertEqual(self.countJobResults(self.history, 'SUCCESS'), 3)

    def test_statsd(self):
        "Test each of the statsd methods used in the scheduler"
        import extras
        statsd = extras.try_import('statsd.statsd')
        statsd.incr('test-incr')
        statsd.timing('test-timing', 3)
        statsd.gauge('test-guage', 12)
        self.assertReportedStat('test-incr', '1|c')
        self.assertReportedStat('test-timing', '3|ms')
        self.assertReportedStat('test-guage', '12|g')

    def test_stuck_job_cleanup(self):
        "Test that pending jobs are cleaned up if removed from layout"
        # This job won't be registered at startup because it is not in
        # the standard layout, but we need it to already be registerd
        # for when we reconfigure, as that is when Zuul will attempt
        # to run the new job.
        self.worker.registerFunction('build:gate-noop')
        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(len(self.gearman_server.getQueue()), 1)

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-no-jobs.yaml')
        self.sched.reconfigure(self.config)
        self.waitUntilSettled()

        self.gearman_server.release('gate-noop')
        self.waitUntilSettled()
        self.assertEqual(len(self.gearman_server.getQueue()), 0)
        self.assertTrue(self.sched._areAllBuildsComplete())

        self.assertEqual(len(self.history), 1)
        self.assertEqual(self.history[0].name, 'gate-noop')
        self.assertEqual(self.history[0].result, 'SUCCESS')

    def test_file_jobs(self):
        "Test that file jobs run only when appropriate"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset(['pip-requires'])
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        testfile_jobs = [x for x in self.history
                         if x.name == 'project-testfile']

        self.assertEqual(len(testfile_jobs), 1)
        self.assertEqual(testfile_jobs[0].changes, '1,2')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_test_config(self):
        "Test that we can test the config"
        sched = zuul.scheduler.Scheduler()
        sched.registerTrigger(None, 'gerrit')
        sched.registerTrigger(None, 'timer')
        sched.testConfig(CONFIG.get('zuul', 'layout_config'))

    def test_build_description(self):
        "Test that build descriptions update"
        self.worker.registerFunction('set_description:' +
                                     self.worker.worker_id)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        desc = self.history[0].description
        self.log.debug("Description: %s" % desc)
        self.assertTrue(re.search("Branch.*master", desc))
        self.assertTrue(re.search("Pipeline.*gate", desc))
        self.assertTrue(re.search("project-merge.*SUCCESS", desc))
        self.assertTrue(re.search("project-test1.*SUCCESS", desc))
        self.assertTrue(re.search("project-test2.*SUCCESS", desc))
        self.assertTrue(re.search("Reported result.*SUCCESS", desc))

    def test_queue_precedence(self):
        "Test that queue precedence works"

        self.gearman_server.hold_jobs_in_queue = True
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        # Run one build at a time to ensure non-race order:
        for x in range(6):
            self.release(self.builds[0])
            self.waitUntilSettled()
        self.worker.hold_jobs_in_build = False
        self.waitUntilSettled()

        self.log.debug(self.history)
        self.assertEqual(self.history[0].pipeline, 'gate')
        self.assertEqual(self.history[1].pipeline, 'check')
        self.assertEqual(self.history[2].pipeline, 'gate')
        self.assertEqual(self.history[3].pipeline, 'gate')
        self.assertEqual(self.history[4].pipeline, 'check')
        self.assertEqual(self.history[5].pipeline, 'check')

    def test_json_status(self, compressed=False):
        "Test that we can retrieve JSON status info"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        port = self.webapp.server.socket.getsockname()[1]

        req = urllib2.Request("http://localhost:%s/status.json" % port)
        if compressed:
            req.add_header("accept-encoding", "gzip")
        f = urllib2.urlopen(req)
        data = f.read()
        if compressed:
            gz = gzip.GzipFile(fileobj=StringIO(data))
            data = gz.read()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        data = json.loads(data)
        status_jobs = set()
        for p in data['pipelines']:
            for q in p['change_queues']:
                if q['dependent']:
                    self.assertEqual(q['window'], 20)
                else:
                    self.assertEqual(q['window'], 0)
                for head in q['heads']:
                    for change in head:
                        self.assertTrue(change['active'])
                        self.assertEqual(change['id'], '1,1')
                        for job in change['jobs']:
                            status_jobs.add(job['name'])
        self.assertIn('project-merge', status_jobs)
        self.assertIn('project-test1', status_jobs)
        self.assertIn('project-test2', status_jobs)

    def test_json_status_gzip(self):
        self.test_json_status(True)

    def test_merging_queues(self):
        "Test that transitively-connected change queues are merged"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-queues.yaml')
        self.sched.reconfigure(self.config)
        self.assertEqual(len(self.sched.layout.pipelines['gate'].queues), 1)

    def test_node_label(self):
        "Test that a job runs on a specific node label"
        self.worker.registerFunction('build:node-project-test1:debian')

        A = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'debian')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

    def test_live_reconfiguration(self):
        "Test that live reconfiguration works"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.sched.reconfigure(self.config)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_live_reconfiguration_functions(self):
        "Test live reconfiguration with a custom function"
        self.worker.registerFunction('build:node-project-test1:debian')
        self.worker.registerFunction('build:node-project-test1:wheezy')
        A = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'debian')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-live-'
                        'reconfiguration-functions.yaml')
        self.sched.reconfigure(self.config)
        self.worker.build_history = []

        B = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'B')
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertIsNone(self.getJobFromHistory('node-project-merge').node)
        self.assertEqual(self.getJobFromHistory('node-project-test1').node,
                         'wheezy')
        self.assertIsNone(self.getJobFromHistory('node-project-test2').node)

    def test_delayed_repo_init(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-delayed-repo-init.yaml')
        self.sched.reconfigure(self.config)

        self.init_repo("org/new-project")
        A = self.fake_gerrit.addFakeChange('org/new-project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

    def test_repo_deleted(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-repo-deleted.yaml')
        self.sched.reconfigure(self.config)

        self.init_repo("org/delete-project")
        A = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

        # Delete org/new-project zuul repo. Should be recloned.
        shutil.rmtree(os.path.join(self.git_root, "org/delete-project"))

        B = self.fake_gerrit.addFakeChange('org/delete-project', 'master', 'B')

        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)

    def test_timer(self):
        "Test that a periodic job is triggered"
        self.worker.hold_jobs_in_build = True
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-timer.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        start = time.time()
        failed = True
        while ((time.time() - start) < 30):
            if len(self.builds) == 2:
                failed = False
                break
            else:
                time.sleep(1)

        if failed:
            raise Exception("Expected jobs never ran")

        self.waitUntilSettled()
        port = self.webapp.server.socket.getsockname()[1]

        f = urllib.urlopen("http://localhost:%s/status.json" % port)
        data = f.read()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-old').result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-older').result, 'SUCCESS')

        data = json.loads(data)
        status_jobs = set()
        for p in data['pipelines']:
            for q in p['change_queues']:
                for head in q['heads']:
                    for change in head:
                        self.assertEqual(change['id'], None)
                        for job in change['jobs']:
                            status_jobs.add(job['name'])
        self.assertIn('project-bitrot-stable-old', status_jobs)
        self.assertIn('project-bitrot-stable-older', status_jobs)

    def test_idle(self):
        "Test that frequent periodic jobs work"
        self.worker.hold_jobs_in_build = True
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-idle.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # The pipeline triggers every second, so we should have seen
        # several by now.
        time.sleep(5)
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 2)
        self.worker.release('.*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 2)

        time.sleep(5)
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(len(self.history), 2)
        self.worker.release('.*')
        self.waitUntilSettled()
        self.assertEqual(len(self.builds), 0)
        self.assertEqual(len(self.history), 4)

    def test_check_smtp_pool(self):
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-smtp.yaml')
        self.sched.reconfigure(self.config)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertEqual(len(self.smtp_messages), 2)

        # A.messages only holds what FakeGerrit places in it. Thus we
        # work on the knowledge of what the first message should be as
        # it is only configured to go to SMTP.

        self.assertEqual('zuul@example.com',
                         self.smtp_messages[0]['from_email'])
        self.assertEqual(['you@example.com'],
                         self.smtp_messages[0]['to_email'])
        self.assertEqual('Starting check jobs.',
                         self.smtp_messages[0]['body'])

        self.assertEqual('zuul_from@example.com',
                         self.smtp_messages[1]['from_email'])
        self.assertEqual(['alternative_me@example.com'],
                         self.smtp_messages[1]['to_email'])
        self.assertEqual(A.messages[0],
                         self.smtp_messages[1]['body'])

    def test_timer_smtp(self):
        "Test that a periodic job is triggered"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-timer-smtp.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        start = time.time()
        failed = True
        while ((time.time() - start) < 30):
            if len(self.history) == 2:
                failed = False
                break
            else:
                time.sleep(1)

        if failed:
            raise Exception("Expected jobs never ran")

        self.waitUntilSettled()

        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-old').result, 'SUCCESS')
        self.assertEqual(self.getJobFromHistory(
            'project-bitrot-stable-older').result, 'SUCCESS')

        self.assertEqual(len(self.smtp_messages), 1)

        # A.messages only holds what FakeGerrit places in it. Thus we
        # work on the knowledge of what the first message should be as
        # it is only configured to go to SMTP.

        self.assertEqual('zuul_from@example.com',
                         self.smtp_messages[0]['from_email'])
        self.assertEqual(['alternative_me@example.com'],
                         self.smtp_messages[0]['to_email'])
        self.assertIn('Subject: Periodic check for org/project succeeded',
                      self.smtp_messages[0]['headers'])

    def test_client_enqueue(self):
        "Test that the RPC client can enqueue a change"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        A.addApproval('APRV', 1)

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.enqueue(pipeline='gate',
                           project='org/project',
                           trigger='gerrit',
                           change='1,1')
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(r, True)

    def test_client_enqueue_negative(self):
        "Test that the RPC client returns errors"
        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid project"):
            r = client.enqueue(pipeline='gate',
                               project='project-does-not-exist',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid pipeline"):
            r = client.enqueue(pipeline='pipeline-does-not-exist',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid trigger"):
            r = client.enqueue(pipeline='gate',
                               project='org/project',
                               trigger='trigger-does-not-exist',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure,
                                         "Invalid change"):
            r = client.enqueue(pipeline='gate',
                               project='org/project',
                               trigger='gerrit',
                               change='1,1')
            client.shutdown()
            self.assertEqual(r, False)

        self.waitUntilSettled()
        self.assertEqual(len(self.history), 0)
        self.assertEqual(len(self.builds), 0)

    def test_client_promote(self):
        "Test that the RPC client can promote a change"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        items = self.sched.layout.pipelines['gate'].getAllItems()
        enqueue_times = {}
        for item in items:
            enqueue_times[str(item.change)] = item.enqueue_time

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.promote(pipeline='gate',
                           change_ids=['2,1', '3,1'])

        # ensure that enqueue times are durable
        items = self.sched.layout.pipelines['gate'].getAllItems()
        for item in items:
            self.assertEqual(
                enqueue_times[str(item.change)], item.enqueue_time)

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], B))
        self.assertFalse(self.job_has_changes(self.builds[0], A))
        self.assertFalse(self.job_has_changes(self.builds[0], C))

        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))
        self.assertFalse(self.job_has_changes(self.builds[2], A))

        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))
        self.assertTrue(self.job_has_changes(self.builds[4], A))

        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        client.shutdown()
        self.assertEqual(r, True)

    def test_client_promote_dependent(self):
        "Test that the RPC client can promote a dependent change"
        # C (depends on B) -> B -> A ; then promote C to get:
        # A -> C (depends on B) -> B
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)
        r = client.promote(pipeline='gate',
                           change_ids=['3,1'])

        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        self.assertEqual(len(self.builds), 6)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')
        self.assertEqual(self.builds[4].name, 'project-test1')
        self.assertEqual(self.builds[5].name, 'project-test2')

        self.assertTrue(self.job_has_changes(self.builds[0], B))
        self.assertFalse(self.job_has_changes(self.builds[0], A))
        self.assertFalse(self.job_has_changes(self.builds[0], C))

        self.assertTrue(self.job_has_changes(self.builds[2], B))
        self.assertTrue(self.job_has_changes(self.builds[2], C))
        self.assertFalse(self.job_has_changes(self.builds[2], A))

        self.assertTrue(self.job_has_changes(self.builds[4], B))
        self.assertTrue(self.job_has_changes(self.builds[4], C))
        self.assertTrue(self.job_has_changes(self.builds[4], A))

        self.worker.release()
        self.waitUntilSettled()

        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)
        self.assertEqual(B.data['status'], 'MERGED')
        self.assertEqual(B.reported, 2)
        self.assertEqual(C.data['status'], 'MERGED')
        self.assertEqual(C.reported, 2)

        client.shutdown()
        self.assertEqual(r, True)

    def test_client_promote_negative(self):
        "Test that the RPC client returns errors for promotion"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(pipeline='nonexistent',
                               change_ids=['2,1', '3,1'])
            client.shutdown()
            self.assertEqual(r, False)

        with testtools.ExpectedException(zuul.rpcclient.RPCFailure):
            r = client.promote(pipeline='gate',
                               change_ids=['4,1'])
            client.shutdown()
            self.assertEqual(r, False)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_queue_rate_limiting(self):
        "Test that DependentPipelines are rate limited with dep across window"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-rate-limit.yaml')
        self.sched.reconfigure(self.config)
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        C.setDependsOn(B, 1)
        self.worker.addFailTest('project-test1', A)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        queue = self.sched.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')

        # Gate is reset and only B's merge job is queued because
        # window shrunk to 1.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only B's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # B was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(B.data['status'], 'MERGED')

        # Only C is left and its merge job is queued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # After successful merge job the test jobs for C are queued.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # C successfully merged so window is bumped to 3.
        self.assertEqual(queue.window, 3)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    def test_queue_rate_limiting_dependent(self):
        "Test that DependentPipelines are rate limited with dep in window"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-rate-limit.yaml')
        self.sched.reconfigure(self.config)
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')

        B.setDependsOn(A, 1)

        self.worker.addFailTest('project-test1', A)

        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        # Only A and B will have their merge jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-merge')
        self.assertEqual(self.builds[1].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only A and B will have their test jobs queued because
        # window is 2.
        self.assertEqual(len(self.builds), 4)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')
        self.assertEqual(self.builds[2].name, 'project-test1')
        self.assertEqual(self.builds[3].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        queue = self.sched.layout.pipelines['gate'].queues[0]
        # A failed so window is reduced by 1 to 1.
        self.assertEqual(queue.window, 1)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(A.data['status'], 'NEW')
        self.assertEqual(B.data['status'], 'NEW')

        # Gate is reset and only C's merge job is queued because
        # window shrunk to 1 and A and B were dequeued.
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.builds[0].name, 'project-merge')

        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # Only C's test jobs are queued because window is still 1.
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.builds[0].name, 'project-test1')
        self.assertEqual(self.builds[1].name, 'project-test2')

        self.worker.release('project-.*')
        self.waitUntilSettled()

        # C was successfully merged so window is increased to 2.
        self.assertEqual(queue.window, 2)
        self.assertEqual(queue.window_floor, 1)
        self.assertEqual(C.data['status'], 'MERGED')

    def test_worker_update_metadata(self):
        "Test if a worker can send back metadata about itself"
        self.worker.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(len(self.launcher.builds), 1)

        self.log.debug('Current builds:')
        self.log.debug(self.launcher.builds)

        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = self.launcher.builds.values()[0]
            if build.worker.name == "My Worker":
                break
            else:
                time.sleep(0)

        self.log.debug(build)
        self.assertEqual("My Worker", build.worker.name)
        self.assertEqual("localhost", build.worker.hostname)
        self.assertEqual(['127.0.0.1', '192.168.1.1'], build.worker.ips)
        self.assertEqual("zuul.example.org", build.worker.fqdn)
        self.assertEqual("FakeBuilder", build.worker.program)
        self.assertEqual("v1.1", build.worker.version)
        self.assertEqual({'something': 'else'}, build.worker.extra)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_footer_message(self):
        "Test a pipeline's footer message is correctly added to the report."
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-footer-message.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('test1', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(2, len(self.smtp_messages))

        failure_body = """\
Build failed.  For information on how to proceed, see \
http://wiki.example.org/Test_Failures

- test1 http://logs.example.com/1/1/gate/test1/0 : FAILURE in 0s
- test2 http://logs.example.com/1/1/gate/test2/1 : SUCCESS in 0s

For CI problems and help debugging, contact ci@example.org"""

        success_body = """\
Build succeeded.

- test1 http://logs.example.com/2/1/gate/test1/2 : SUCCESS in 0s
- test2 http://logs.example.com/2/1/gate/test2/3 : SUCCESS in 0s

For CI problems and help debugging, contact ci@example.org"""

        self.assertEqual(failure_body, self.smtp_messages[0]['body'])
        self.assertEqual(success_body, self.smtp_messages[1]['body'])

    def test_merge_failure_reporters(self):
        """Check that the config is set up correctly"""

        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-failure.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        self.assertEqual(
            "Merge Failed.\n\nThis change was unable to be automatically "
            "merged with the current state of the repository. Please rebase "
            "your change and upload a new patchset.",
            self.sched.layout.pipelines['check'].merge_failure_message)
        self.assertEqual(
            "The merge failed! For more information...",
            self.sched.layout.pipelines['gate'].merge_failure_message)

        self.assertEqual(
            len(self.sched.layout.pipelines['check'].merge_failure_actions), 1)
        self.assertEqual(
            len(self.sched.layout.pipelines['gate'].merge_failure_actions), 2)

        self.assertTrue(isinstance(
            self.sched.layout.pipelines['check'].merge_failure_actions[0].
            reporter, zuul.reporter.gerrit.Reporter))

        self.assertTrue(
            (
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[0].reporter,
                           zuul.reporter.smtp.Reporter) and
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[1].reporter,
                           zuul.reporter.gerrit.Reporter)
            ) or (
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[0].reporter,
                           zuul.reporter.gerrit.Reporter) and
                isinstance(self.sched.layout.pipelines['gate'].
                           merge_failure_actions[1].reporter,
                           zuul.reporter.smtp.Reporter)
            )
        )

    def test_merge_failure_reports(self):
        """Check that when a change fails to merge the correct message is sent
        to the correct reporter"""
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-merge-failure.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        # Check a test failure isn't reported to SMTP
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('project-test1', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(3, len(self.history))  # 3 jobs
        self.assertEqual(0, len(self.smtp_messages))

        # Check a merge failure is reported to SMTP
        # B should be merged, but C will conflict with B
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset(['conflict'])
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        C.addPatchset(['conflict'])
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(6, len(self.history))  # A and B jobs
        self.assertEqual(1, len(self.smtp_messages))
        self.assertEqual('The merge failed! For more information...',
                         self.smtp_messages[0]['body'])

    def test_swift_instructions(self):
        "Test that the correct swift instructions are sent to the workers"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-swift.yaml')
        self.sched.reconfigure(self.config)
        self.registerJobs()

        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/merge_logs/1/1/1/"
            "gate/test-merge/",
            self.builds[0].parameters['SWIFT_logs_URL'][:-32])
        self.assertEqual(5,
                         len(self.builds[0].parameters['SWIFT_logs_HMAC_BODY'].
                             split('\n')))
        self.assertIn('SWIFT_logs_SIGNATURE', self.builds[0].parameters)

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/logs/1/1/1/"
            "gate/test-test/",
            self.builds[1].parameters['SWIFT_logs_URL'][:-32])
        self.assertEqual(5,
                         len(self.builds[1].parameters['SWIFT_logs_HMAC_BODY'].
                             split('\n')))
        self.assertIn('SWIFT_logs_SIGNATURE', self.builds[1].parameters)

        self.assertEqual(
            "https://storage.example.org/V1/AUTH_account/stash/1/1/1/"
            "gate/test-test/",
            self.builds[1].parameters['SWIFT_MOSTLY_URL'][:-32])
        self.assertEqual(5,
                         len(self.builds[1].
                             parameters['SWIFT_MOSTLY_HMAC_BODY'].split('\n')))
        self.assertIn('SWIFT_MOSTLY_SIGNATURE', self.builds[1].parameters)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

    def test_client_get_running_jobs(self):
        "Test that the RPC client can get a list of running jobs"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        client = zuul.rpcclient.RPCClient('127.0.0.1',
                                          self.gearman_server.port)

        # Wait for gearman server to send the initial workData back to zuul
        start = time.time()
        while True:
            if time.time() - start > 10:
                raise Exception("Timeout waiting for gearman server to report "
                                + "back to the client")
            build = self.launcher.builds.values()[0]
            if build.worker.name == "My Worker":
                break
            else:
                time.sleep(0)

        running_items = client.get_running_jobs()

        self.assertEqual(1, len(running_items))
        running_item = running_items[0]
        self.assertEqual([], running_item['failing_reasons'])
        self.assertEqual([], running_item['items_behind'])
        self.assertEqual('https://hostname/1', running_item['url'])
        self.assertEqual(None, running_item['item_ahead'])
        self.assertEqual('org/project', running_item['project'])
        self.assertEqual(None, running_item['remaining_time'])
        self.assertEqual(True, running_item['active'])
        self.assertEqual('1,1', running_item['id'])

        self.assertEqual(3, len(running_item['jobs']))
        for job in running_item['jobs']:
            if job['name'] == 'project-merge':
                self.assertEqual('project-merge', job['name'])
                self.assertEqual('gate', job['pipeline'])
                self.assertEqual(False, job['retry'])
                self.assertEqual(13, len(job['parameters']))
                self.assertEqual('https://server/job/project-merge/0/',
                                 job['url'])
                self.assertEqual(7, len(job['worker']))
                self.assertEqual(False, job['canceled'])
                self.assertEqual(True, job['voting'])
                self.assertEqual(None, job['result'])
                self.assertEqual('gate', job['pipeline'])
                break

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        running_items = client.get_running_jobs()
        self.assertEqual(0, len(running_items))
