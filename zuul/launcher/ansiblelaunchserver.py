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

import json
import logging
import multiprocessing
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import traceback

import gear
import yaml
import jenkins_jobs.builder


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


class LaunchServer(object):
    log = logging.getLogger("zuul.LaunchServer")

    def __init__(self, config):
        self.config = config
        self.hostname = socket.gethostname()
        self.node_workers = {}
        self.mpmanager = multiprocessing.Manager()
        self.jobs = self.mpmanager.dict()

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
        self.loadJobs()
        self.log.debug("Starting worker")
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def loadJobs(self):
        self.log.debug("Loading jobs")
        builder = JJB()
        path = self.config.get('launcher', 'jenkins_jobs')
        builder.load_files([path])
        builder.parser.expandYaml()
        unseen = set(self.jobs.keys())
        for job in builder.parser.jobs:
            self.jobs[job['name']] = job
            unseen.discard(job['name'])
        for name in unseen:
            del self.jobs[name]

    def register(self):
        self.worker.registerFunction("node-assign:zuul")

    def reconfigure(self, config):
        self.log.debug("Reconfiguring")
        self.config = config
        self.loadJobs()
        for node in self.node_workers.values():
            node.queue.put(dict(action='reconfigure'))

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self.worker.shutdown()
        for node in self.node_workers.values():
            node.queue.put(dict(action='stop'))
        self.log.debug("Stopped")

    def join(self):
        self.thread.join()

    def run(self):
        self.log.debug("Starting launch listener")
        while self._running:
            try:
                job = self.worker.getJob()
                try:
                    if job.name.startswith('node-assign:'):
                        self.log.debug("Got assign-node job: %s" % job.unique)
                        self.assignNode(job)
                    else:
                        self.log.error("Unable to handle job %s" % job.name)
                        job.sendWorkFail()
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(traceback.format_exc())
            except Exception:
                self.log.exception("Exception while getting job")

    def assignNode(self, job):
        args = json.loads(job.arguments)
        worker = NodeWorker(self.config, self.jobs,
                            args['name'], args['host'],
                            args['description'], args['labels'])
        self.node_workers[worker.name] = worker

        worker.process = multiprocessing.Process(target=worker.run)
        worker.process.start()

        data = dict(manager=self.hostname)
        job.sendWorkData(json.dumps(data))
        job.sendWorkComplete()


class NodeWorker(object):
    log = logging.getLogger("zuul.NodeWorker")

    def __init__(self, config, jobs, name, host, description, labels):
        self.config = config
        self.jobs = jobs
        self.name = name
        self.host = host
        self.description = description
        if not isinstance(labels, list):
            labels = [labels]
        self.labels = labels
        self.registered_functions = set()
        self._running = True
        self.queue = multiprocessing.Queue()

    def run(self):
        self._running_job = False
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.worker = gear.Worker(self.name)
        self.worker.addServer(server, port)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.register()

        self.gearman_thread = threading.Thread(target=self.run_gearman)
        self.gearman_thread.daemon = True
        self.gearman_thread.start()

        while self._running:
            try:
                self._run_queue()
            except Exception:
                self.log.exception("Exception in queue manager:")

    def _run_queue(self):
        item = self.queue.get()
        if item['action'] == 'stop':
            self._running = False
            self.worker.shutdown()
        elif item['action'] == 'reconfigure':
            self.register()

    def run_gearman(self):
        while self._running:
            try:
                self._run_gearman()
            except Exception:
                self.log.exception("Exception in gearman manager:")

    def _run_gearman(self):
        job = self.worker.getJob()
        try:
            if job.name not in self.registered_functions:
                self.log.error("Unable to handle job %s" % job.name)
                job.sendWorkFail()
                return
            self.launch(job)
        except Exception:
            self.log.exception("Exception while running job")
            job.sendWorkException(traceback.format_exc())

    def generateFunctionNames(self, job):
        # This only supports "node: foo" and "node: foo || bar"
        ret = set()
        job_labels = job.get('node')
        matching_labels = set()
        if job_labels:
            job_labels = [x.strip() for x in job_labels.split('||')]
            matching_labels = set(self.labels) & set(job_labels)
            if not matching_labels:
                return ret
        ret.add('build:%s' % (job['name'],))
        for label in matching_labels:
            ret.add('build:%s:%s' % (job['name'], label))
        return ret

    def register(self):
        if self._running_job:
            return
        new_functions = set()
        for job in self.jobs.values():
            new_functions |= self.generateFunctionNames(job)
        for function in new_functions - self.registered_functions:
            self.worker.registerFunction(function)
        for function in self.registered_functions - new_functions:
            self.worker.unRegisterFunction(function)
        self.registered_functions = new_functions

    def launch(self, job):
        self._running_job = True
        thread = threading.Thread(target=self._launch, args=(job,))
        thread.start()

    def _launch(self, job):
        self.log.debug("Job %s: beginning" % (job.unique,))
        return  # TODO
        with JobDir() as jobdir:
            self.log.debug("Job %s: job root at %s" %
                           (job.unique, jobdir.root))
            args = json.loads(job.arguments)

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


class JJB(jenkins_jobs.builder.Builder):
    def __init__(self):
        self.global_config = None
        self._plugins_list = []
