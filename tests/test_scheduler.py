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
import tempfile
import threading
import time
import urllib
import urllib2
import urlparse

import git
import gear
import fixtures
import statsd
import testtools

import zuul.scheduler
import zuul.webapp
import zuul.launcher.gearman
import zuul.trigger.gerrit

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
    output = subprocess.Popen(
        ['git', '--git-dir=%s/.git' % path, 'repack', '-afd'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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

        return repo.index.commit(msg)

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

    def addApproval(self, category, value):
        approval = {'description': self.categories[category][0],
                    'type': category,
                    'value': str(value)}
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
        change = self.changes[int(number)]
        return change.query()

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
            }

        self.job.sendWorkData(json.dumps(data))
        self.job.sendWorkStatus(0, 100)

        if self.worker.hold_jobs_in_build:
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

        data = {'result': result}
        changes = None
        if 'ZUUL_CHANGE_IDS' in self.parameters:
            changes = self.parameters['ZUUL_CHANGE_IDS']

        self.worker.build_history.append(
            BuildHistory(name=self.name, number=self.number,
                         result=result, changes=changes, node=self.node,
                         uuid=self.unique, description=self.description)
            )

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
        for queue in [self.high_queue, self.normal_queue, self.low_queue]:
            queue = queue[:]
            for job in queue:
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
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))

        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
            os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
            os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))
        self.useFixture(fixtures.NestedTempfile())
        if (os.environ.get('OS_LOG_CAPTURE') == 'True' or
            os.environ.get('OS_LOG_CAPTURE') == '1'):
            self.useFixture(fixtures.FakeLogger(
                level=logging.DEBUG,
                format='%(asctime)s %(name)-32s '
                '%(levelname)-8s %(message)s'))
        tmp_root = tempfile.mkdtemp(dir=os.environ.get("ZUUL_TEST_ROOT",
                                                       '/tmp'))
        self.test_root = os.path.join(tmp_root, "zuul-test")
        self.upstream_root = os.path.join(self.test_root, "upstream")
        self.git_root = os.path.join(self.test_root, "git")

        CONFIG.set('zuul', 'git_dir', self.git_root)
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
        self.init_repo("org/node-project")

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

        self.sched = zuul.scheduler.Scheduler()

        def URLOpenerFactory(*args, **kw):
            args = [self.fake_gerrit] + list(args)
            return FakeURLOpener(self.upstream_root, *args, **kw)

        urllib2.urlopen = URLOpenerFactory
        self.launcher = zuul.launcher.gearman.Gearman(self.config, self.sched)

        zuul.lib.gerrit.Gerrit = FakeGerrit

        self.gerrit = FakeGerritTrigger(
            self.upstream_root, self.config, self.sched)
        self.gerrit.replication_timeout = 1.5
        self.gerrit.replication_retry_interval = 0.5
        self.fake_gerrit = self.gerrit.gerrit
        self.fake_gerrit.upstream_root = self.upstream_root

        self.webapp = zuul.webapp.WebApp(self.sched, port=0)

        self.sched.setLauncher(self.launcher)
        self.sched.setTrigger(self.gerrit)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()
        self.webapp.start()
        self.launcher.gearman.waitForServer()
        self.registerJobs()
        self.builds = self.worker.running_builds
        self.history = self.worker.build_history

        self.addCleanup(self.assertFinalState)
        self.addCleanup(self.shutdown)

    def assertFinalState(self):
        # Make sure that the change cache is cleared
        assert len(self.sched.trigger._change_cache.keys()) == 0
        self.assertEmptyQueues()

    def shutdown(self):
        self.log.debug("Shutting down after tests")
        self.launcher.stop()
        self.worker.shutdown()
        self.gearman_server.shutdown()
        self.gerrit.stop()
        self.sched.stop()
        self.sched.join()
        self.statsd.stop()
        self.statsd.join()
        self.webapp.stop()
        self.webapp.join()
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
        for msg in commit_messages:
            if msg not in repo_messages:
                return False
        if repo_shas[0] != sha:
            return False
        return True

    def registerJobs(self):
        count = 0
        for job in self.sched.jobs.keys():
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
                if connection.functions:
                    done = False
            if done:
                break
            time.sleep(0)
        self.gearman_server.functions = set()

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
                if (self.sched.trigger_event_queue.empty() and
                    self.sched.result_event_queue.empty() and
                    self.fake_gerrit.event_queue.empty() and
                    self.areAllBuildsWaiting()):
                    self.worker.lock.release()
                    self.log.debug("...settled.")
                    return
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
        for pipeline in self.sched.pipelines.values():
            for queue in pipeline.queues:
                if len(queue.queue) != 0:
                    print 'pipeline %s queue %s contents %s' % (
                        pipeline.name, queue.name, queue.queue)
                assert len(queue.queue) == 0
                if len(queue.severed_heads) != 0:
                    print 'heads', queue.severed_heads
                assert len(queue.severed_heads) == 0

    def assertReportedStat(self, key, value=None):
        start = time.time()
        while time.time() < (start + 5):
            for stat in self.statsd.stats:
                k, v = stat.split(':')
                if key == k:
                    if value is None:
                        return
                    if value == v:
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
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2

        self.assertReportedStat('gerrit.event.comment-added', '1|c')
        self.assertReportedStat('zuul.pipeline.gate.current_changes', '1|g')
        self.assertReportedStat('zuul.job.project-merge')
        self.assertReportedStat('zuul.pipeline.gate.resident_time')
        self.assertReportedStat('zuul.pipeline.gate.total_changes', '1|c')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.resident_time')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.total_changes', '1|c')

    def test_duplicate_pipelines(self):
        "Test that a change matching multiple pipelines works"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getChangeRestoredEvent())
        self.waitUntilSettled()

        assert len(self.history) == 2
        self.history[0].name == 'project-test1'
        self.history[1].name == 'project-test1'

        assert len(A.messages) == 2
        if 'dup1/project-test1' in A.messages[0]:
            assert 'dup1/project-test1' in A.messages[0]
            assert 'dup2/project-test1' not in A.messages[0]
            assert 'dup1/project-test1' not in A.messages[1]
            assert 'dup2/project-test1' in A.messages[1]
        else:
            assert 'dup1/project-test1' in A.messages[1]
            assert 'dup2/project-test1' not in A.messages[1]
            assert 'dup1/project-test1' not in A.messages[0]
            assert 'dup2/project-test1' in A.messages[0]

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
        assert len(self.builds) == 1
        assert self.builds[0].name == 'project-merge'
        assert self.job_has_changes(self.builds[0], A)

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        assert len(self.builds) == 3
        assert self.builds[0].name == 'project-test1'
        assert self.job_has_changes(self.builds[0], A)
        assert self.builds[1].name == 'project-test2'
        assert self.job_has_changes(self.builds[1], A)
        assert self.builds[2].name == 'project-merge'
        assert self.job_has_changes(self.builds[2], A, B)

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        assert len(self.builds) == 5
        assert self.builds[0].name == 'project-test1'
        assert self.job_has_changes(self.builds[0], A)
        assert self.builds[1].name == 'project-test2'
        assert self.job_has_changes(self.builds[1], A)

        assert self.builds[2].name == 'project-test1'
        assert self.job_has_changes(self.builds[2], A, B)
        assert self.builds[3].name == 'project-test2'
        assert self.job_has_changes(self.builds[3], A, B)

        assert self.builds[4].name == 'project-merge'
        assert self.job_has_changes(self.builds[4], A, B, C)

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        assert len(self.builds) == 6
        assert self.builds[0].name == 'project-test1'
        assert self.job_has_changes(self.builds[0], A)
        assert self.builds[1].name == 'project-test2'
        assert self.job_has_changes(self.builds[1], A)

        assert self.builds[2].name == 'project-test1'
        assert self.job_has_changes(self.builds[2], A, B)
        assert self.builds[3].name == 'project-test2'
        assert self.job_has_changes(self.builds[3], A, B)

        assert self.builds[4].name == 'project-test1'
        assert self.job_has_changes(self.builds[4], A, B, C)
        assert self.builds[5].name == 'project-test2'
        assert self.job_has_changes(self.builds[5], A, B, C)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
        assert len(self.builds) == 0

        assert len(self.history) == 9
        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

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
        assert len(self.history) > 6
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2

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
        assert len(self.builds) == 2
        assert self.builds[0].name == 'project-merge'
        assert self.job_has_changes(self.builds[0], A)
        assert self.builds[1].name == 'project1-merge'
        assert self.job_has_changes(self.builds[1], B)

        # Release the current merge builds
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        # Release the merge job for project2 which is behind project1
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        # All the test builds should be running:
        # project1 (3) + project2 (3) + project (2) = 8
        assert len(self.builds) == 8

        self.worker.release()
        self.waitUntilSettled()
        assert len(self.builds) == 0

        assert len(self.history) == 11
        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

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

        assert len(self.builds) == 1
        assert self.builds[0].name == 'project-merge'
        assert self.job_has_changes(self.builds[0], A)

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        assert len(self.builds) == 6
        assert self.builds[0].name == 'project-test1'
        assert self.builds[1].name == 'project-test2'
        assert self.builds[2].name == 'project-test1'
        assert self.builds[3].name == 'project-test2'
        assert self.builds[4].name == 'project-test1'
        assert self.builds[5].name == 'project-test2'

        self.release(self.builds[0])
        self.waitUntilSettled()

        assert len(self.builds) == 2  # project-test2, project-merge for B
        assert self.countJobResults(self.history, 'ABORTED') == 4

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        assert len(self.builds) == 0
        assert len(self.history) == 15
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

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
        assert len(self.builds) == 0
        assert len(queue) == 1
        assert queue[0].name == 'build:project-merge'
        assert self.job_has_changes(queue[0], A)

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()

        assert len(self.builds) == 0
        assert len(queue) == 6
        assert queue[0].name == 'build:project-test1'
        assert queue[1].name == 'build:project-test2'
        assert queue[2].name == 'build:project-test1'
        assert queue[3].name == 'build:project-test2'
        assert queue[4].name == 'build:project-test1'
        assert queue[5].name == 'build:project-test2'

        self.release(queue[0])
        self.waitUntilSettled()

        assert len(self.builds) == 0
        queue = self.gearman_server.getQueue()
        assert len(queue) == 2  # project-test2, project-merge for B
        assert self.countJobResults(self.history, 'ABORTED') == 0

        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        assert len(self.builds) == 0
        assert len(self.history) == 11
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

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

        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'NEW'
        assert C.data['status'] == 'NEW'

        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()
        assert M2.queried == 0
        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

    def test_can_merge(self):
        "Test whether a change is ready to merge"
        # TODO: move to test_gerrit (this is a unit test!)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        a = self.sched.trigger.getChange(1, 2)
        mgr = self.sched.pipelines['gate'].manager
        assert not self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())

        A.addApproval('CRVW', 2)
        a = self.sched.trigger.getChange(1, 2, refresh=True)
        assert not self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())

        A.addApproval('APRV', 1)
        a = self.sched.trigger.getChange(1, 2, refresh=True)
        assert self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())
        self.sched.trigger.maintainCache([])

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
        assert repo_messages == correct_messages

    def test_build_configuration_conflict(self):
        "Test that merge conflicts are handled"

        self.gearman_server.hold_jobs_in_queue = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addPatchset(['conflict'])
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        B.addPatchset(['conflict'])
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
        self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'NEW'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

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
        assert len(self.history) == 1
        assert 'project-post' in job_names

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
        assert repo_messages == correct_messages

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

        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref_mp = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        self.gearman_server.release('.*-merge')
        self.waitUntilSettled()
        queue = self.gearman_server.getQueue()
        ref_master = self.getParameter(queue[-1], 'ZUUL_REF')
        self.gearman_server.hold_jobs_in_queue = False
        self.gearman_server.release()
        self.waitUntilSettled()

        path = os.path.join(self.git_root, "org/project")
        repo = git.Repo(path)

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_master)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'C-1']
        assert repo_messages == correct_messages

        repo_messages = [c.message.strip()
                         for c in repo.iter_commits(ref_mp)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'B-1']
        assert repo_messages == correct_messages

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

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'MERGED'
        assert B.reported == 2

    def test_job_from_templates_launched(self):
        "Test whether a job generated via a template can be launched"

        A = self.fake_gerrit.addFakeChange(
            'org/templated-project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'

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

        assert A.data['status'] == 'NEW'
        assert A.reported == 2
        assert B.data['status'] == 'NEW'
        assert B.reported == 2
        assert C.data['status'] == 'NEW'
        assert C.reported == 2
        assert len(self.history) == 1

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

        assert len(self.builds) == 1
        assert self.builds[0].name == 'project1-merge'
        assert self.job_has_changes(self.builds[0], A)

        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()
        self.worker.release('.*-merge')
        self.waitUntilSettled()

        assert len(self.builds) == 9
        assert self.builds[0].name == 'project1-test1'
        assert self.builds[1].name == 'project1-test2'
        assert self.builds[2].name == 'project1-project2-integration'
        assert self.builds[3].name == 'project1-test1'
        assert self.builds[4].name == 'project1-test2'
        assert self.builds[5].name == 'project1-project2-integration'
        assert self.builds[6].name == 'project1-test1'
        assert self.builds[7].name == 'project1-test2'
        assert self.builds[8].name == 'project1-project2-integration'

        self.release(self.builds[0])
        self.waitUntilSettled()

        assert len(self.builds) == 3  # test2, integration, merge for B
        assert self.countJobResults(self.history, 'ABORTED') == 6

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        assert len(self.builds) == 0
        assert len(self.history) == 20

        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2

    def test_nonvoting_job(self):
        "Test that non-voting jobs don't vote."

        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        A.addApproval('CRVW', 2)
        self.worker.addFailTest('nonvoting-project-test2', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert (self.getJobFromHistory('nonvoting-project-merge').result ==
                'SUCCESS')
        assert (self.getJobFromHistory('nonvoting-project-test1').result ==
                'SUCCESS')
        assert (self.getJobFromHistory('nonvoting-project-test2').result ==
                'FAILURE')

    def test_check_queue_success(self):
        "Test successful check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        assert A.data['status'] == 'NEW'
        assert A.reported == 1
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'

    def test_check_queue_failure(self):
        "Test failed check queue jobs."

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.worker.addFailTest('project-test2', A)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        assert A.data['status'] == 'NEW'
        assert A.reported == 1
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'FAILURE'

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

        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert D.data['status'] == 'MERGED'
        assert E.data['status'] == 'MERGED'
        assert F.data['status'] == 'MERGED'

        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        assert D.reported == 2
        assert E.reported == 2
        assert F.reported == 2

        assert self.countJobResults(self.history, 'ABORTED') == 15
        assert len(self.history) == 44

    def test_merger_repack(self):
        "Test that the merger works after a repack"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()
        self.worker.build_history = []

        path = os.path.join(self.git_root, "org/project")
        print repack_repo(path)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2

    def test_merger_repack_large_change(self):
        "Test that the merger works with large changes after a repack"
        # https://bugs.launchpad.net/zuul/+bug/1078946
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addPatchset(large=True)
        path = os.path.join(self.upstream_root, "org/project1")
        print repack_repo(path)
        path = os.path.join(self.git_root, "org/project1")
        print repack_repo(path)

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        assert self.getJobFromHistory('project1-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project1-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project1-test2').result == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2

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
        assert not job_names
        assert A.data['status'] == 'NEW'
        assert A.reported == 2
        self.assertEmptyQueues()

        # Make sure things still work:
        self.registerJobs()
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        assert self.getJobFromHistory('project-merge').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test1').result == 'SUCCESS'
        assert self.getJobFromHistory('project-test2').result == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2

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

        assert len(self.history) == 0

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

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'NEW'
        assert B.reported == 2
        assert C.data['status'] == 'NEW'
        assert C.reported == 2
        assert D.data['status'] == 'MERGED'
        assert D.reported == 2
        assert len(self.history) == 9  # 3 each for A, B, D.

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

        assert A.data['status'] == 'NEW'
        assert A.reported == 2
        assert B.data['status'] == 'NEW'
        assert B.reported == 2
        assert C.data['status'] == 'NEW'
        assert C.reported == 2
        assert D.data['status'] == 'MERGED'
        assert D.reported == 2
        assert len(self.history) == 7

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

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'NEW'
        assert B.reported == 2
        assert C.data['status'] == 'MERGED'
        assert C.reported == 2
        assert len(self.history) == 9

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

        assert A.data['status'] == 'NEW'
        assert A.reported == 1
        assert B.data['status'] == 'NEW'
        assert B.reported == 1
        assert C.data['status'] == 'NEW'
        assert C.reported == 1
        assert len(self.history) == 10
        assert self.countJobResults(self.history, 'ABORTED') == 1

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
        assert a_zref is not None
        assert b_zref is not None
        assert c_zref is not None
        assert d_zref is not None

        # And they should all be different
        refs = set([a_zref, b_zref, c_zref, d_zref])
        assert len(refs) == 4

        # a ref should have a, not b, and should not be in project2
        assert self.ref_has_change(a_zref, A)
        assert not self.ref_has_change(a_zref, B)
        assert not self.ref_has_change(a_zref, M2)

        # b ref should have a and b, and should not be in project2
        assert self.ref_has_change(b_zref, A)
        assert self.ref_has_change(b_zref, B)
        assert not self.ref_has_change(b_zref, M2)

        # c ref should have a and b in 1, c in 2
        assert self.ref_has_change(c_zref, A)
        assert self.ref_has_change(c_zref, B)
        assert self.ref_has_change(c_zref, C)
        assert not self.ref_has_change(c_zref, D)

        # d ref should have a and b in 1, c and d in 2
        assert self.ref_has_change(d_zref, A)
        assert self.ref_has_change(d_zref, B)
        assert self.ref_has_change(d_zref, C)
        assert self.ref_has_change(d_zref, D)

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'MERGED'
        assert B.reported == 2
        assert C.data['status'] == 'MERGED'
        assert C.reported == 2
        assert D.data['status'] == 'MERGED'
        assert D.reported == 2

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

        assert len(testfile_jobs) == 1
        assert testfile_jobs[0].changes == '1,2'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'MERGED'
        assert B.reported == 2

    def test_test_config(self):
        "Test that we can test the config"
        sched = zuul.scheduler.Scheduler()
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
        assert re.search("Branch.*master", desc)
        assert re.search("Pipeline.*gate", desc)
        assert re.search("project-merge.*SUCCESS", desc)
        assert re.search("project-test1.*SUCCESS", desc)
        assert re.search("project-test2.*SUCCESS", desc)
        assert re.search("Reported result.*SUCCESS", desc)

    def test_json_status(self):
        "Test that we can retrieve JSON status info"
        self.worker.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        port = self.webapp.server.socket.getsockname()[1]

        f = urllib.urlopen("http://localhost:%s/status.json" % port)
        data = f.read()

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()

        data = json.loads(data)
        status_jobs = set()
        for p in data['pipelines']:
            for q in p['change_queues']:
                for head in q['heads']:
                    for change in head:
                        assert change['id'] == '1,1'
                        for job in change['jobs']:
                            status_jobs.add(job['name'])
        assert 'project-merge' in status_jobs
        assert 'project-test1' in status_jobs
        assert 'project-test2' in status_jobs

    def test_node_label(self):
        "Test that a job runs on a specific node label"
        self.worker.registerFunction('build:node-project-test1:debian')

        A = self.fake_gerrit.addFakeChange('org/node-project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()

        assert self.getJobFromHistory('node-project-merge').node is None
        assert self.getJobFromHistory('node-project-test1').node == 'debian'
        assert self.getJobFromHistory('node-project-test2').node is None
