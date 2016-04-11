# Copyright 2014 OpenStack Foundation
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

import collections
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import traceback

import gear
import yaml

import zuul.merger


class JobDir(object):
    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.git_root = os.path.join(self.root, 'git')
        os.makedirs(self.git_root)
        self.ansible_root = os.path.join(self.root, 'ansible')
        os.makedirs(self.ansible_root)
        self.inventory = os.path.join(self.ansible_root, 'inventory')
        self.playbook = os.path.join(self.ansible_root, 'playbook')
        self.config = os.path.join(self.ansible_root, 'ansible.cfg')

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        shutil.rmtree(self.root)


class UpdateTask(object):
    def __init__(self, project, url):
        self.project = project
        self.url = url
        self.event = threading.Event()

    def __eq__(self, other):
        if other.project == self.project:
            return True
        return False

    def wait(self):
        self.event.wait()

    def setComplete(self):
        self.event.set()


class DeduplicateQueue(object):
    def __init__(self):
        self.queue = collections.deque()
        self.condition = threading.Condition()

    def qsize(self):
        return len(self.queue)

    def put(self, item):
        # Returns the original item if added, or an equivalent item if
        # already enqueued.
        self.condition.acquire()
        ret = None
        try:
            for x in self.queue:
                if item == x:
                    ret = x
            if ret is None:
                ret = item
                self.queue.append(item)
                self.condition.notify()
        finally:
            self.condition.release()
        return ret

    def get(self):
        self.condition.acquire()
        try:
            while True:
                try:
                    ret = self.queue.popleft()
                    return ret
                except IndexError:
                    pass
                self.condition.wait()
        finally:
            self.condition.release()


class LaunchServer(object):
    log = logging.getLogger("zuul.LaunchServer")

    def __init__(self, config, connections={}):
        self.config = config
        self.zuul_url = config.get('merger', 'zuul_url')

        if self.config.has_option('merger', 'git_dir'):
            self.merge_root = self.config.get('merger', 'git_dir')
        else:
            self.merge_root = '/var/lib/zuul/git'

        if self.config.has_option('merger', 'git_user_email'):
            self.merge_email = self.config.get('merger', 'git_user_email')
        else:
            self.merge_email = None

        if self.config.has_option('merger', 'git_user_name'):
            self.merge_name = self.config.get('merger', 'git_user_name')
        else:
            self.merge_name = None

        self.connections = connections
        self.merger = self._getMerger(self.merge_root)
        self.update_queue = DeduplicateQueue()

    def _getMerger(self, root):
        return zuul.merger.merger.Merger(root, self.connections,
                                         self.merge_email, self.merge_name)

    def start(self):
        self._running = True
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.worker = gear.Worker('Zuul Launch Server')
        self.worker.addServer(server, port)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.log.debug("Registering")
        self.register()
        self.log.debug("Starting worker")
        self.update_thread = threading.Thread(target=self._updateLoop)
        self.update_thread.daemon = True
        self.update_thread.start()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("launcher:launch")
        # TODOv3: abort
        self.worker.registerFunction("merger:cat")

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self.worker.shutdown()
        self.log.debug("Stopped")

    def join(self):
        self.update_thread.join()
        self.thread.join()

    def _updateLoop(self):
        while self._running:
            try:
                self._innerUpdateLoop()
            except:
                self.log.exception("Exception in update thread:")

    def _innerUpdateLoop(self):
        # Inside of a loop that keeps the main repository up to date
        task = self.update_queue.get()
        self.log.info("Updating repo %s from %s" % (task.project, task.url))
        self.merger.updateRepo(task.project, task.url)
        self.log.debug("Finished updating repo %s from %s" %
                       (task.project, task.url))
        task.setComplete()

    def update(self, project, url):
        task = UpdateTask(project, url)
        task = self.update_queue.put(task)
        return task

    def run(self):
        self.log.debug("Starting launch listener")
        while self._running:
            try:
                job = self.worker.getJob()
                try:
                    if job.name == 'launcher:launch':
                        self.log.debug("Got launch job: %s" % job.unique)
                        self.launch(job)
                    elif job.name == 'merger:cat':
                        self.log.debug("Got cat job: %s" % job.unique)
                        self.cat(job)
                    else:
                        self.log.error("Unable to handle job %s" % job.name)
                        job.sendWorkFail()
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(traceback.format_exc())
            except Exception:
                self.log.exception("Exception while getting job")

    def launch(self, job):
        thread = threading.Thread(target=self._launch, args=(job,))
        thread.start()

    def _launch(self, job):
        self.log.debug("Job %s: beginning" % (job.unique,))
        with JobDir() as jobdir:
            self.log.debug("Job %s: job root at %s" %
                           (job.unique, jobdir.root))
            args = json.loads(job.arguments)
            tasks = []
            for project in args['projects']:
                self.log.debug("Job %s: updating project %s" %
                               (job.unique, project['name']))
                tasks.append(self.update(project['name'], project['url']))
            for task in tasks:
                task.wait()
            self.log.debug("Job %s: git updates complete" % (job.unique,))
            merger = self._getMerger(jobdir.git_root)
            commit = merger.mergeChanges(args['items'])  # noqa

            # TODOv3: Ansible the ansible thing here.
            self.prepareAnsibleFiles(jobdir, args)
            result = self.runAnsible(jobdir)

            data = {
                'url': 'https://server/job',
                'number': 1
            }
            job.sendWorkData(json.dumps(data))
            job.sendWorkStatus(0, 100)

            result = dict(result=result)
            job.sendWorkComplete(json.dumps(result))

    def getHostList(self, args):
        # TODOv3: This should get the appropriate nodes from nodepool,
        # or in the unit tests, be overriden to return localhost.
        return [('localhost', dict(ansible_connection='local'))]

    def prepareAnsibleFiles(self, jobdir, args):
        with open(jobdir.inventory, 'w') as inventory:
            for host_name, host_vars in self.getHostList(args):
                inventory.write(host_name)
                inventory.write(' ')
                for k, v in host_vars.items():
                    inventory.write('%s=%s' % (k, v))
                inventory.write('\n')
        with open(jobdir.playbook, 'w') as playbook:
            play = dict(hosts='localhost',
                        tasks=[dict(name='test',
                                    shell='echo Hello world')])
            playbook.write(yaml.dump([play]))
        with open(jobdir.config, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % jobdir.inventory)

    def runAnsible(self, jobdir):
        proc = subprocess.Popen(
            ['ansible-playbook', jobdir.playbook],
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (out, err) = proc.communicate()
        ret = proc.wait()
        print out
        print err
        if ret == 0:
            return 'SUCCESS'
        else:
            return 'FAILURE'

    def cat(self, job):
        args = json.loads(job.arguments)
        task = self.update(args['project'], args['url'])
        task.wait()
        files = self.merger.getFiles(args['project'], args['url'],
                                     args['branch'], args['files'])
        result = dict(updated=True,
                      files=files,
                      zuul_url=self.zuul_url)
        job.sendWorkComplete(json.dumps(result))
