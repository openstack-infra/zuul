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

import unittest
import ConfigParser
import os
import Queue
import hashlib
import logging
import random
import json
import threading
import time
import pprint
import re
import urllib2
import urlparse
import shutil
import string
import git

import zuul
import zuul.scheduler
import zuul.launcher.jenkins
import zuul.trigger.gerrit

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
CONFIG = ConfigParser.ConfigParser()
CONFIG.read(os.path.join(FIXTURE_DIR, "zuul.conf"))

CONFIG.set('zuul', 'layout_config',
           os.path.join(FIXTURE_DIR, "layout.yaml"))

TMP_ROOT = os.environ.get("ZUUL_TEST_ROOT", "/tmp")
TEST_ROOT = os.path.join(TMP_ROOT, "zuul-test")
UPSTREAM_ROOT = os.path.join(TEST_ROOT, "upstream")
GIT_ROOT = os.path.join(TEST_ROOT, "git")

CONFIG.set('zuul', 'git_dir', GIT_ROOT)

logging.basicConfig(level=logging.DEBUG)


def random_sha1():
    return hashlib.sha1(str(random.random())).hexdigest()


class ChangeReference(git.Reference):
    _common_path_default = "refs/changes"
    _points_to_commits_only = True


def init_repo(project):
    parts = project.split('/')
    path = os.path.join(UPSTREAM_ROOT, *parts[:-1])
    if not os.path.exists(path):
        os.makedirs(path)
    path = os.path.join(UPSTREAM_ROOT, project)
    repo = git.Repo.init(path)

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


def add_fake_change_to_repo(project, branch, change_num, patchset, msg, fn,
                            large):
    path = os.path.join(UPSTREAM_ROOT, project)
    repo = git.Repo(path)
    ref = ChangeReference.create(repo, '1/%s/%s' % (change_num,
                                                    patchset),
                                 'refs/tags/init')
    repo.head.reference = ref
    repo.head.reset(index=True, working_tree=True)
    repo.git.clean('-x', '-f', '-d')

    path = os.path.join(UPSTREAM_ROOT, project)
    if not large:
        fn = os.path.join(path, fn)
        f = open(fn, 'w')
        f.write("test %s %s %s\n" % (branch, change_num, patchset))
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


def ref_has_change(ref, change):
    path = os.path.join(GIT_ROOT, change.project)
    repo = git.Repo(path)
    for commit in repo.iter_commits(ref):
        if commit.message.strip() == ('%s-1' % change.subject):
            return True
    return False


def job_has_changes(*args):
    job = args[0]
    commits = args[1:]
    project = job.parameters['ZUUL_PROJECT']
    path = os.path.join(GIT_ROOT, project)
    repo = git.Repo(path)
    ref = job.parameters['ZUUL_REF']
    sha = job.parameters['ZUUL_COMMIT']
    repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
    repo_shas = [c.hexsha for c in repo.iter_commits(ref)]
    commit_messages = ['%s-1' % commit.subject for commit in commits]
    for msg in commit_messages:
        if msg not in repo_messages:
            return False
    if repo_shas[0] != sha:
        return False
    return True


class FakeChange(object):
    categories = {'APRV': ('Approved', -1, 1),
                  'CRVW': ('Code-Review', -2, 2),
                  'VRFY': ('Verified', -2, 2)}

    def __init__(self, gerrit, number, project, branch, subject, status='NEW'):
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

        self.addPatchset()
        self.data['submitRecords'] = self.getSubmitRecords()

    def addPatchset(self, files=None, large=False):
        self.latest_patchset += 1
        if files:
            fn = files[0]
        else:
            fn = '%s-%s' % (self.branch, self.number)
        msg = self.subject + '-' + str(self.latest_patchset)
        c = add_fake_change_to_repo(self.project, self.branch,
                                    self.number, self.latest_patchset,
                                    msg, fn, large)
        d = {'approvals': [],
             'createdOn': time.time(),
             'files': [{'file': '/COMMIT_MSG',
                        'type': 'ADDED'},
                       {'file': 'README',
                        'type': 'MODIFIED'}],
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

        path = os.path.join(UPSTREAM_ROOT, self.project)
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
        c = FakeChange(self, self.change_number, project, branch, subject)
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
        if 'submit' in action:
            change.setMerged()
        if message:
            change.setReported()

    def query(self, number):
        change = self.changes[int(number)]
        return change.query()

    def startWatching(self, *args, **kw):
        pass


class FakeJenkinsEvent(object):
    def __init__(self, name, number, parameters, phase, status=None):
        data = {
            'build': {
                'full_url': 'https://server/job/%s/%s/' % (name, number),
                'number': number,
                'parameters': parameters,
                'phase': phase,
                'url': 'job/%s/%s/' % (name, number),
            },
            'name': name,
            'url': 'job/%s/' % name,
        }
        if status:
            data['build']['status'] = status
        self.body = json.dumps(data)


class FakeJenkinsJob(threading.Thread):
    log = logging.getLogger("zuul.test")

    def __init__(self, jenkins, callback, name, number, parameters):
        threading.Thread.__init__(self)
        self.jenkins = jenkins
        self.callback = callback
        self.name = name
        self.number = number
        self.parameters = parameters
        self.wait_condition = threading.Condition()
        self.waiting = False
        self.aborted = False
        self.canceled = False
        self.created = time.time()

    def release(self):
        self.wait_condition.acquire()
        self.wait_condition.notify()
        self.waiting = False
        self.log.debug("Job %s released" % (self.parameters['UUID']))
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
        self.log.debug("Job %s waiting" % (self.parameters['UUID']))
        self.wait_condition.wait()
        self.wait_condition.release()

    def run(self):
        self.jenkins.fakeEnqueue(self)
        if self.jenkins.hold_jobs_in_queue:
            self._wait()
        self.jenkins.fakeDequeue(self)
        if self.canceled:
            self.jenkins.all_jobs.remove(self)
            return
        self.callback.jenkins_endpoint(FakeJenkinsEvent(self.name,
                                                        self.number,
                                                        self.parameters,
                                                        'STARTED'))
        if self.jenkins.hold_jobs_in_build:
            self._wait()
        self.log.debug("Job %s continuing" % (self.parameters['UUID']))

        result = 'SUCCESS'
        if (('ZUUL_REF' in self.parameters) and
            self.jenkins.fakeShouldFailTest(self.name,
                                            self.parameters['ZUUL_REF'])):
            result = 'FAILURE'
        if self.aborted:
            result = 'ABORTED'

        self.jenkins.fakeAddHistory(name=self.name, number=self.number,
                                    result=result)
        self.callback.jenkins_endpoint(FakeJenkinsEvent(self.name,
                                                        self.number,
                                                        self.parameters,
                                                        'COMPLETED',
                                                        result))
        self.callback.jenkins_endpoint(FakeJenkinsEvent(self.name,
                                                        self.number,
                                                        self.parameters,
                                                        'FINISHED',
                                                        result))
        self.jenkins.all_jobs.remove(self)


class FakeJenkins(object):
    log = logging.getLogger("zuul.test")

    def __init__(self, *args, **kw):
        self.queue = []
        self.all_jobs = []
        self.job_counter = {}
        self.queue_counter = 0
        self.job_history = []
        self.hold_jobs_in_queue = False
        self.hold_jobs_in_build = False
        self.fail_tests = {}
        self.nonexistent_jobs = []

    def fakeEnqueue(self, job):
        self.queue.append(job)

    def fakeDequeue(self, job):
        self.queue.remove(job)

    def fakeAddHistory(self, **kw):
        self.job_history.append(kw)

    def fakeRelease(self, regex=None):
        all_jobs = self.all_jobs[:]
        self.log.debug("releasing jobs %s (%s)" % (regex, len(self.all_jobs)))
        for job in all_jobs:
            if not regex or re.match(regex, job.name):
                self.log.debug("releasing job %s" % (job.parameters['UUID']))
                job.release()
            else:
                self.log.debug("not releasing job %s" %
                               (job.parameters['UUID']))
        self.log.debug("done releasing jobs %s (%s)" % (regex,
                                                        len(self.all_jobs)))

    def fakeAllWaiting(self, regex=None):
        all_jobs = self.all_jobs[:] + self.queue[:]
        for job in all_jobs:
            self.log.debug("job %s %s" % (job.parameters['UUID'],
                                          job.isWaiting()))
            if not job.isWaiting():
                return False
        return True

    def fakeAddFailTest(self, name, change):
        l = self.fail_tests.get(name, [])
        l.append(change)
        self.fail_tests[name] = l

    def fakeShouldFailTest(self, name, ref):
        l = self.fail_tests.get(name, [])
        for change in l:
            if ref_has_change(ref, change):
                return True
        return False

    def build_job(self, name, parameters):
        if name in self.nonexistent_jobs:
            raise Exception("Job does not exist")
        count = self.job_counter.get(name, 0)
        count += 1
        self.job_counter[name] = count

        queue_count = self.queue_counter
        self.queue_counter += 1
        job = FakeJenkinsJob(self, self.callback, name, count, parameters)
        job.queue_id = queue_count

        self.all_jobs.append(job)
        job.start()

    def stop_build(self, name, number):
        for job in self.all_jobs:
            if job.name == name and job.number == number:
                job.aborted = True
                job.release()
                return

    def cancel_queue(self, id):
        for job in self.queue:
            if job.queue_id == id:
                job.canceled = True
                job.release()
                return

    def get_queue_info(self):
        items = []
        for job in self.queue:
            paramstr = ''
            paramlst = []
            d = {'actions': [{'parameters': paramlst},
                             {'causes': [{'shortDescription':
                                          'Started by user Jenkins',
                                          'userId': 'jenkins',
                                          'userName': 'Jenkins'}]}],
                 'blocked': False,
                 'buildable': True,
                 'buildableStartMilliseconds': (job.created * 1000) + 5,
                 'id': job.queue_id,
                 'inQueueSince': (job.created * 1000),
                 'params': paramstr,
                 'stuck': False,
                 'task': {'color': 'blue',
                          'name': job.name,
                          'url': 'https://server/job/%s/' % job.name},
                 'why': 'Waiting for next available executor'}
            for k, v in job.parameters.items():
                paramstr += "\n(StringParameterValue) %s='%s'" % (k, v)
                pd = {'name': k, 'value': v}
                paramlst.append(pd)
            items.append(d)
        return items

    def set_build_description(self, *args, **kw):
        pass


class FakeJenkinsCallback(zuul.launcher.jenkins.JenkinsCallback):
    def start(self):
        pass


class FakeURLOpener(object):
    def __init__(self, fake_gerrit, url):
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
        path = os.path.join(UPSTREAM_ROOT, project)
        repo = git.Repo(path)
        for ref in repo.refs:
            r = ref.object.hexsha + ' ' + ref.path + '\n'
            ret += '%04x%s' % (len(r) + 4, r)
        ret += '0000'
        return ret


class FakeGerritTrigger(zuul.trigger.gerrit.Gerrit):
    def getGitUrl(self, project):
        return os.path.join(UPSTREAM_ROOT, project.name)


class testScheduler(unittest.TestCase):
    log = logging.getLogger("zuul.test")

    def setUp(self):
        if os.path.exists(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        os.makedirs(TEST_ROOT)
        os.makedirs(UPSTREAM_ROOT)
        os.makedirs(GIT_ROOT)

        # For each project in config:
        init_repo("org/project")
        init_repo("org/project1")
        init_repo("org/project2")
        init_repo("org/project3")
        init_repo("org/one-job-project")
        init_repo("org/nonvoting-project")
        self.config = CONFIG
        self.sched = zuul.scheduler.Scheduler()

        def jenkinsFactory(*args, **kw):
            self.fake_jenkins = FakeJenkins()
            return self.fake_jenkins

        def jenkinsCallbackFactory(*args, **kw):
            self.fake_jenkins_callback = FakeJenkinsCallback(*args, **kw)
            return self.fake_jenkins_callback

        def URLOpenerFactory(*args, **kw):
            args = [self.fake_gerrit] + list(args)
            return FakeURLOpener(*args, **kw)

        zuul.launcher.jenkins.ExtendedJenkins = jenkinsFactory
        zuul.launcher.jenkins.JenkinsCallback = jenkinsCallbackFactory
        urllib2.urlopen = URLOpenerFactory
        self.jenkins = zuul.launcher.jenkins.Jenkins(self.config, self.sched)
        self.fake_jenkins.callback = self.fake_jenkins_callback

        zuul.lib.gerrit.Gerrit = FakeGerrit

        self.gerrit = FakeGerritTrigger(self.config, self.sched)
        self.gerrit.replication_timeout = 1.5
        self.gerrit.replication_retry_interval = 0.5
        self.fake_gerrit = self.gerrit.gerrit

        self.sched.setLauncher(self.jenkins)
        self.sched.setTrigger(self.gerrit)

        self.sched.start()
        self.sched.reconfigure(self.config)
        self.sched.resume()

    def tearDown(self):
        self.jenkins.stop()
        self.gerrit.stop()
        self.sched.stop()
        self.sched.join()
        #shutil.rmtree(TEST_ROOT)

    def waitUntilSettled(self):
        self.log.debug("Waiting until settled...")
        start = time.time()
        while True:
            if time.time() - start > 10:
                print 'queue status:',
                print self.sched.trigger_event_queue.empty(),
                print self.sched.result_event_queue.empty(),
                print self.fake_gerrit.event_queue.empty(),
                raise Exception("Timeout waiting for Zuul to settle")
            self.fake_gerrit.event_queue.join()
            self.sched.queue_lock.acquire()
            if (self.sched.trigger_event_queue.empty() and
                self.sched.result_event_queue.empty() and
                self.fake_gerrit.event_queue.empty() and
                self.fake_jenkins.fakeAllWaiting()):
                self.sched.queue_lock.release()
                self.log.debug("...settled.")
                return
            self.sched.queue_lock.release()
            self.sched.wake_event.wait(0.1)

    def countJobResults(self, jobs, result):
        jobs = filter(lambda x: x['result'] == result, jobs)
        return len(jobs)

    def assertEmptyQueues(self):
        # Make sure there are no orphaned jobs
        for pipeline in self.sched.pipelines.values():
            for queue in pipeline.queues:
                if len(queue.queue) != 0:
                    print 'queue', queue.queue
                assert len(queue.queue) == 0
                if len(queue.severed_heads) != 0:
                    print 'heads', queue.severed_heads
                assert len(queue.severed_heads) == 0

    def test_jobs_launched(self):
        "Test that jobs are launched and a change is merged"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert 'project-merge' in job_names
        assert 'project-test1' in job_names
        assert 'project-test2' in job_names
        assert jobs[0]['result'] == 'SUCCESS'
        assert jobs[1]['result'] == 'SUCCESS'
        assert jobs[2]['result'] == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()

    def test_parallel_changes(self):
        "Test that changes are tested in parallel and merged in series"
        self.fake_jenkins.hold_jobs_in_build = True
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
        jobs = self.fake_jenkins.all_jobs
        assert len(jobs) == 1
        assert jobs[0].name == 'project-merge'
        assert job_has_changes(jobs[0], A)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        assert len(jobs) == 3
        assert jobs[0].name == 'project-test1'
        assert job_has_changes(jobs[0], A)
        assert jobs[1].name == 'project-test2'
        assert job_has_changes(jobs[1], A)
        assert jobs[2].name == 'project-merge'
        assert job_has_changes(jobs[2], A, B)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        assert len(jobs) == 5
        assert jobs[0].name == 'project-test1'
        assert job_has_changes(jobs[0], A)
        assert jobs[1].name == 'project-test2'
        assert job_has_changes(jobs[1], A)

        assert jobs[2].name == 'project-test1'
        assert job_has_changes(jobs[2], A, B)
        assert jobs[3].name == 'project-test2'
        assert job_has_changes(jobs[3], A, B)

        assert jobs[4].name == 'project-merge'
        assert job_has_changes(jobs[4], A, B, C)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        assert len(jobs) == 6
        assert jobs[0].name == 'project-test1'
        assert job_has_changes(jobs[0], A)
        assert jobs[1].name == 'project-test2'
        assert job_has_changes(jobs[1], A)

        assert jobs[2].name == 'project-test1'
        assert job_has_changes(jobs[2], A, B)
        assert jobs[3].name == 'project-test2'
        assert job_has_changes(jobs[3], A, B)

        assert jobs[4].name == 'project-test1'
        assert job_has_changes(jobs[4], A, B, C)
        assert jobs[5].name == 'project-test2'
        assert job_has_changes(jobs[5], A, B, C)

        self.fake_jenkins.hold_jobs_in_build = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()
        assert len(jobs) == 0

        jobs = self.fake_jenkins.job_history
        assert len(jobs) == 9
        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

    def test_failed_changes(self):
        "Test that a change behind a failed change is retested"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))

        self.fake_jenkins.fakeAddFailTest('project-test1', A)

        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        assert len(jobs) > 6
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        self.assertEmptyQueues()

    def test_independent_queues(self):
        "Test that changes end up in the right queues"
        self.fake_jenkins.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project2', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        jobs = self.fake_jenkins.all_jobs
        self.waitUntilSettled()

        # There should be one merge job at the head of each queue running
        assert len(jobs) == 2
        assert jobs[0].name == 'project-merge'
        assert job_has_changes(jobs[0], A)
        assert jobs[1].name == 'project1-merge'
        assert job_has_changes(jobs[1], B)

        # Release the current merge jobs
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        # Release the merge job for project2 which is behind project1
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        # All the test jobs should be running:
        # project1 (3) + project2 (3) + project (2) = 8
        assert len(jobs) == 8

        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()
        assert len(jobs) == 0

        jobs = self.fake_jenkins.job_history
        assert len(jobs) == 11
        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

    def test_failed_change_at_head(self):
        "Test that if a change at the head fails, jobs behind it are canceled"
        self.fake_jenkins.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_jenkins.fakeAddFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert len(jobs) == 1
        assert jobs[0].name == 'project-merge'
        assert job_has_changes(jobs[0], A)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        assert len(jobs) == 6
        assert jobs[0].name == 'project-test1'
        assert jobs[1].name == 'project-test2'
        assert jobs[2].name == 'project-test1'
        assert jobs[3].name == 'project-test2'
        assert jobs[4].name == 'project-test1'
        assert jobs[5].name == 'project-test2'

        jobs[0].release()
        self.waitUntilSettled()

        assert len(jobs) == 2  # project-test2, project-merge for B
        assert self.countJobResults(finished_jobs, 'ABORTED') == 4

        self.fake_jenkins.hold_jobs_in_build = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        assert len(jobs) == 0
        assert len(finished_jobs) == 15
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

    def test_failed_change_at_head_with_queue(self):
        "Test that if a change at the head fails, queued jobs are canceled"
        self.fake_jenkins.hold_jobs_in_queue = True

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_jenkins.fakeAddFailTest('project-test1', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history
        queue = self.fake_jenkins.queue

        assert len(jobs) == 1
        assert len(queue) == 1
        assert jobs[0].name == 'project-merge'
        assert job_has_changes(jobs[0], A)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        assert len(jobs) == 6
        assert len(queue) == 6
        assert jobs[0].name == 'project-test1'
        assert jobs[1].name == 'project-test2'
        assert jobs[2].name == 'project-test1'
        assert jobs[3].name == 'project-test2'
        assert jobs[4].name == 'project-test1'
        assert jobs[5].name == 'project-test2'

        jobs[0].release()
        self.waitUntilSettled()

        assert len(jobs) == 2  # project-test2, project-merge for B
        assert len(queue) == 2
        assert self.countJobResults(finished_jobs, 'ABORTED') == 0

        self.fake_jenkins.hold_jobs_in_queue = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        assert len(jobs) == 0
        assert len(finished_jobs) == 11
        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

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
        self.assertEmptyQueues()

    def test_can_merge(self):
        "Test whether a change is ready to merge"
        # TODO: move to test_gerrit (this is a unit test!)
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        a = self.sched.trigger.getChange(1, 2)
        mgr = self.sched.pipelines['gate'].manager
        assert not self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())

        A.addApproval('CRVW', 2)
        a = self.sched.trigger.getChange(1, 2)
        assert not self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())

        A.addApproval('APRV', 1)
        a = self.sched.trigger.getChange(1, 2)
        assert self.sched.trigger.canMerge(a, mgr.getSubmitAllowNeeds())
        self.assertEmptyQueues()

    def test_build_configuration(self):
        "Test that zuul merges the right commits for testing"
        self.fake_jenkins.hold_jobs_in_queue = True
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

        jobs = self.fake_jenkins.all_jobs

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        ref = jobs[-1].parameters['ZUUL_REF']
        self.fake_jenkins.hold_jobs_in_queue = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        path = os.path.join(GIT_ROOT, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'A-1', 'B-1', 'C-1']
        assert repo_messages == correct_messages
        self.assertEmptyQueues()

    def test_build_configuration_conflict(self):
        "Test that merge conflicts are handled"
        self.fake_jenkins.hold_jobs_in_queue = True
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

        jobs = self.fake_jenkins.all_jobs

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        ref = jobs[-1].parameters['ZUUL_REF']
        self.fake_jenkins.hold_jobs_in_queue = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        assert A.data['status'] == 'MERGED'
        assert B.data['status'] == 'NEW'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

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

        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert len(jobs) == 1
        assert 'project-post' in job_names
        self.assertEmptyQueues()

    def test_build_configuration_branch(self):
        "Test that the right commits are on alternate branches"
        self.fake_jenkins.hold_jobs_in_queue = True
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

        jobs = self.fake_jenkins.all_jobs

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        ref = jobs[-1].parameters['ZUUL_REF']
        self.fake_jenkins.hold_jobs_in_queue = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        path = os.path.join(GIT_ROOT, "org/project")
        repo = git.Repo(path)
        repo_messages = [c.message.strip() for c in repo.iter_commits(ref)]
        repo_messages.reverse()
        correct_messages = ['initial commit', 'mp commit', 'A-1', 'B-1', 'C-1']
        assert repo_messages == correct_messages
        self.assertEmptyQueues()

    def test_build_configuration_branch_interaction(self):
        "Test that switching between branches works"
        self.test_build_configuration()
        self.test_build_configuration_branch()
        # C has been merged, undo that
        path = os.path.join(UPSTREAM_ROOT, "org/project")
        repo = git.Repo(path)
        repo.heads.master.commit = repo.commit('init')
        self.test_build_configuration()
        self.assertEmptyQueues()

    def test_build_configuration_multi_branch(self):
        "Test that dependent changes on multiple branches are merged"
        self.fake_jenkins.hold_jobs_in_queue = True
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

        jobs = self.fake_jenkins.all_jobs

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        ref_mp = jobs[-1].parameters['ZUUL_REF']
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        ref_master = jobs[-1].parameters['ZUUL_REF']
        self.fake_jenkins.hold_jobs_in_queue = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        path = os.path.join(GIT_ROOT, "org/project")
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
        self.assertEmptyQueues()

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

        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.data['status'] == 'MERGED'
        assert B.reported == 2
        self.assertEmptyQueues()

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

        self.fake_jenkins.fakeAddFailTest('project-merge', A)

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()

        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        for x in jobs:
            print x
        for x in finished_jobs:
            print x

        assert A.data['status'] == 'NEW'
        assert A.reported == 2
        assert B.data['status'] == 'NEW'
        assert B.reported == 2
        assert C.data['status'] == 'NEW'
        assert C.reported == 2
        assert len(finished_jobs) == 1
        self.assertEmptyQueues()

    def test_head_is_dequeued_once(self):
        "Test that if a change at the head fails it is dequeud only once"
        # If it's dequeued more than once, we should see extra
        # aborted jobs.
        self.fake_jenkins.hold_jobs_in_build = True

        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        C = self.fake_gerrit.addFakeChange('org/project1', 'master', 'C')
        A.addApproval('CRVW', 2)
        B.addApproval('CRVW', 2)
        C.addApproval('CRVW', 2)

        self.fake_jenkins.fakeAddFailTest('project1-test1', A)
        self.fake_jenkins.fakeAddFailTest('project1-test2', A)
        self.fake_jenkins.fakeAddFailTest('project1-project2-integration', A)

        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert len(jobs) == 1
        assert jobs[0].name == 'project1-merge'
        assert job_has_changes(jobs[0], A)

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        assert len(jobs) == 9
        assert jobs[0].name == 'project1-test1'
        assert jobs[1].name == 'project1-test2'
        assert jobs[2].name == 'project1-project2-integration'
        assert jobs[3].name == 'project1-test1'
        assert jobs[4].name == 'project1-test2'
        assert jobs[5].name == 'project1-project2-integration'
        assert jobs[6].name == 'project1-test1'
        assert jobs[7].name == 'project1-test2'
        assert jobs[8].name == 'project1-project2-integration'

        jobs[0].release()
        self.waitUntilSettled()

        assert len(jobs) == 3  # test2, integration, merge for B
        assert self.countJobResults(finished_jobs, 'ABORTED') == 6

        self.fake_jenkins.hold_jobs_in_build = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        assert len(jobs) == 0
        assert len(finished_jobs) == 20

        assert A.data['status'] == 'NEW'
        assert B.data['status'] == 'MERGED'
        assert C.data['status'] == 'MERGED'
        assert A.reported == 2
        assert B.reported == 2
        assert C.reported == 2
        self.assertEmptyQueues()

    def test_nonvoting_job(self):
        "Test that non-voting jobs don't vote."
        A = self.fake_gerrit.addFakeChange('org/nonvoting-project',
                                           'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_jenkins.fakeAddFailTest('nonvoting-project-test2', A)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        assert finished_jobs[0]['result'] == 'SUCCESS'
        assert finished_jobs[1]['result'] == 'SUCCESS'
        assert finished_jobs[2]['result'] == 'FAILURE'
        self.assertEmptyQueues()

    def test_check_queue_success(self):
        "Test successful check queue jobs."
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert A.data['status'] == 'NEW'
        assert A.reported == 1
        assert finished_jobs[0]['result'] == 'SUCCESS'
        assert finished_jobs[1]['result'] == 'SUCCESS'
        assert finished_jobs[2]['result'] == 'SUCCESS'
        self.assertEmptyQueues()

    def test_check_queue_failure(self):
        "Test failed check queue jobs."
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_jenkins.fakeAddFailTest('project-test2', A)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        assert A.data['status'] == 'NEW'
        assert A.reported == 1
        assert finished_jobs[0]['result'] == 'SUCCESS'
        assert finished_jobs[1]['result'] == 'SUCCESS'
        assert finished_jobs[2]['result'] == 'FAILURE'
        self.assertEmptyQueues()

    def test_dependent_behind_dequeue(self):
        "test that dependent changes behind dequeued changes work"
        # This complicated test is a reproduction of a real life bug
        self.sched.reconfigure(self.config)
        self.fake_jenkins.hold_jobs_in_build = True

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
        jobs = self.fake_jenkins.all_jobs
        finished_jobs = self.fake_jenkins.job_history

        # Change object re-use in the gerrit trigger is hidden if
        # changes are added in quick succession; waiting makes it more
        # like real life.
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(B.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        self.fake_gerrit.addEvent(C.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(D.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(E.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.fake_gerrit.addEvent(F.addApproval('APRV', 1))
        self.waitUntilSettled()

        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()
        self.fake_jenkins.fakeRelease('.*-merge')
        self.waitUntilSettled()

        for x in jobs:
            print x
        # all jobs running

        # Grab pointers to the jobs we want to release before
        # releasing any, because list indexes may change as
        # the jobs complete.
        a, b, c = jobs[:3]
        a.release()
        b.release()
        c.release()
        self.waitUntilSettled()

        self.fake_jenkins.hold_jobs_in_build = False
        self.fake_jenkins.fakeRelease()
        self.waitUntilSettled()

        for x in jobs:
            print x
        for x in finished_jobs:
            print x
        print self.sched.formatStatusHTML()

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

        assert self.countJobResults(finished_jobs, 'ABORTED') == 15
        assert len(finished_jobs) == 44
        self.assertEmptyQueues()

    def test_merger_repack(self):
        "Test that the merger works after a repack"
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert 'project-merge' in job_names
        assert 'project-test1' in job_names
        assert 'project-test2' in job_names
        assert jobs[0]['result'] == 'SUCCESS'
        assert jobs[1]['result'] == 'SUCCESS'
        assert jobs[2]['result'] == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()

        path = os.path.join(GIT_ROOT, "org/project")
        os.system('git --git-dir=%s/.git repack -afd' % path)

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert 'project-merge' in job_names
        assert 'project-test1' in job_names
        assert 'project-test2' in job_names
        assert jobs[0]['result'] == 'SUCCESS'
        assert jobs[1]['result'] == 'SUCCESS'
        assert jobs[2]['result'] == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()

    def test_merger_repack_large_change(self):
        "Test that the merger works with large changes after a repack"
        # https://bugs.launchpad.net/zuul/+bug/1078946
        A = self.fake_gerrit.addFakeChange('org/project1', 'master', 'A')
        A.addPatchset(large=True)
        path = os.path.join(UPSTREAM_ROOT, "org/project1")
        os.system('git --git-dir=%s/.git repack -afd' % path)
        path = os.path.join(GIT_ROOT, "org/project1")
        os.system('git --git-dir=%s/.git repack -afd' % path)

        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert 'project1-merge' in job_names
        assert 'project1-test1' in job_names
        assert 'project1-test2' in job_names
        assert jobs[0]['result'] == 'SUCCESS'
        assert jobs[1]['result'] == 'SUCCESS'
        assert jobs[2]['result'] == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()

    def test_nonexistent_job(self):
        "Test launching a job that doesn't exist"
        self.fake_jenkins.nonexistent_jobs.append('project-merge')
        self.jenkins.launch_retry_timeout = 0.1

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        # There may be a thread about to report a lost change
        while A.reported < 2:
            self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert not job_names
        assert A.data['status'] == 'NEW'
        assert A.reported == 2
        self.assertEmptyQueues()

        # Make sure things still work:
        self.fake_jenkins.nonexistent_jobs = []
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        jobs = self.fake_jenkins.job_history
        job_names = [x['name'] for x in jobs]
        assert 'project-merge' in job_names
        assert 'project-test1' in job_names
        assert 'project-test2' in job_names
        assert jobs[0]['result'] == 'SUCCESS'
        assert jobs[1]['result'] == 'SUCCESS'
        assert jobs[2]['result'] == 'SUCCESS'
        assert A.data['status'] == 'MERGED'
        assert A.reported == 2
        self.assertEmptyQueues()
