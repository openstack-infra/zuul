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
import signal
import socket
import subprocess
import tempfile
import threading
import traceback
import uuid

import gear
import yaml
import jenkins_jobs.builder
import zmq


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
        self.script_root = os.path.join(self.ansible_root, 'scripts')
        os.makedirs(self.script_root)

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
        self.zmq_send_queue = multiprocessing.Queue()

    def start(self):
        self._running = True

        # Setup ZMQ
        self.zcontext = zmq.Context()
        self.zsocket = self.zcontext.socket(zmq.PUB)
        self.zsocket.bind("tcp://*:8881")

        # Setup Gearman
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

        # Load JJB config
        self.loadJobs()

        # Start ZMQ worker thread
        self.log.debug("Starting ZMQ processor")
        self.zmq_thread = threading.Thread(target=self.run_zmq)
        self.zmq_thread.daemon = True
        self.zmq_thread.start()

        # Start Gearman worker thread
        self.log.debug("Starting worker")
        self.gearman_thread = threading.Thread(target=self.run)
        self.gearman_thread.daemon = True
        self.gearman_thread.start()

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
            node.stop()
        self.log.debug("Stopped")

    def join(self):
        self.gearman_thread.join()

    def run_zmq(self):
        while self._running:
            try:
                item = self.zmq_send_queue.get()
                self.log.debug("Got ZMQ event %s" % (item,))
                if item is None:
                    continue
                self.zsocket.send(item)
            except Exception:
                self.log.exception("Exception while processing ZMQ events")

    def run(self):
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
            except gear.InterruptedError:
                return
            except Exception:
                self.log.exception("Exception while getting job")

    def assignNode(self, job):
        args = json.loads(job.arguments)
        self.log.debug("Assigned node with arguments: %s" % (args,))
        worker = NodeWorker(self.config, self.jobs,
                            args['name'], args['host'],
                            args['description'], args['labels'],
                            self.hostname, self.zmq_send_queue)
        self.node_workers[worker.name] = worker

        worker.process = multiprocessing.Process(target=worker.run)
        worker.process.start()

        data = dict(manager=self.hostname)
        job.sendWorkData(json.dumps(data))
        job.sendWorkComplete()


class NodeWorker(object):
    log = logging.getLogger("zuul.NodeWorker")

    def __init__(self, config, jobs, name, host, description, labels,
                 manager_name, zmq_send_queue):
        self.log.debug("Creating node worker %s" % (name,))
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
        self.manager_name = manager_name
        self.zmq_send_queue = zmq_send_queue
        self.running_job_lock = threading.Lock()
        self._running_job = False
        self._sent_complete_event = False

    def run(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.log.debug("Node worker %s starting" % (self.name,))
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

    def stop(self):
        # If this is called locally, setting _running will be
        # effictive, if it's called remotely, it will not be, but it
        # will be set by the queue thread.
        self.log.debug("Submitting stop request")
        self._running = False
        self.queue.put(dict(action='stop'))

    def _run_queue(self):
        item = self.queue.get()
        if item['action'] == 'stop':
            self.log.debug("Received stop request")
            self._running = False
            self.worker.shutdown()
            if not self.abortRunningJob():
                self.sendFakeCompleteEvent()
        elif item['action'] == 'reconfigure':
            self.register()

    def run_gearman(self):
        while self._running:
            try:
                self._run_gearman()
            except Exception:
                self.log.exception("Exception in gearman manager:")

    def _run_gearman(self):
        try:
            job = self.worker.getJob()
        except gear.InterruptedError:
            return
        self.log.debug("Node worker %s got job %s" % (self.name, job.name))
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

    def abortRunningJob(self):
        aborted = False
        self.log.debug("Abort: acquiring job lock")
        with self.running_job_lock:
            if self._running_job:
                self.log.debug("Abort: a job is running")
                proc = self.ansible_proc
                if proc:
                    self.log.debug("Abort: sending kill signal to job process")
                    try:
                        proc.kill()
                        aborted = True
                    except Exception:
                        self.log.exception("Exception while killing "
                                           "ansible process:")
            else:
                self.log.debug("Abort: no job is running")

        return aborted

    def launch(self, job):
        self.log.debug("Node worker %s launching job %s" %
                       (self.name, job.name))

        # Make sure we can parse what we need from the job first
        args = json.loads(job.arguments)
        # This may be configurable later, or we may choose to honor
        # OFFLINE_NODE_WHEN_COMPLETE
        offline = True
        job_name = job.name.split(':')[1]

        # Initialize the result so we have something regardless of
        # whether the job actually runs
        result = None
        self._sent_complete_event = False

        try:
            self.sendStartEvent(job_name, args)
        except Exception:
            self.log.exception("Exception while sending job start event")

        try:
            result = self.runJob(job)
        except Exception:
            self.log.exception("Exception while launching job thread")

        self._running_job = False
        if not result:
            result = b''

        try:
            job.sendWorkComplete(result)
        except Exception:
            self.log.exception("Exception while sending job completion packet")

        try:
            self.sendCompleteEvent(job_name, result, args)
        except Exception:
            self.log.exception("Exception while sending job completion event")

        if offline:
            self.stop()

    def sendStartEvent(self, name, parameters):
        build = dict(node_name=self.name,
                     host_name=self.manager_name,
                     parameters=parameters)

        event = dict(name=name,
                     build=build)

        item = "onStarted %s" % json.dumps(event)
        self.log.debug("Sending over ZMQ: %s" % (item,))
        self.zmq_send_queue.put(item)

    def sendCompleteEvent(self, name, status, parameters):
        build = dict(status=status,
                     node_name=self.name,
                     host_name=self.manager_name,
                     parameters=parameters)

        event = dict(name=name,
                     build=build)

        item = "onFinalized %s" % json.dumps(event)
        self.log.debug("Sending over ZMQ: %s" % (item,))
        self.zmq_send_queue.put(item)
        self._sent_complete_event = True

    def sendFakeCompleteEvent(self):
        if self._sent_complete_event:
            return
        self.sendCompleteEvent('zuul:launcher-shutdown',
                               'SUCCESS', {})

    def runJob(self, job):
        self.ansible_proc = None
        result = None
        with self.running_job_lock:
            if not self._running:
                return result
            self._running_job = True

        self.log.debug("Job %s: beginning" % (job.unique,))
        with JobDir() as jobdir:
            self.log.debug("Job %s: job root at %s" %
                           (job.unique, jobdir.root))

            self.prepareAnsibleFiles(jobdir, job)
            status = self.runAnsible(jobdir)

            data = {
                'url': 'https://server/job',
                'number': 1
            }
            job.sendWorkData(json.dumps(data))
            job.sendWorkStatus(0, 100)

            result = json.dumps(dict(result=status))

        return result

    def getHostList(self):
        return [('node', dict(ansible_host=self.host))]

    def prepareAnsibleFiles(self, jobdir, gearman_job):
        with open(jobdir.inventory, 'w') as inventory:
            for host_name, host_vars in self.getHostList():
                inventory.write(host_name)
                inventory.write(' ')
                for k, v in host_vars.items():
                    inventory.write('%s=%s' % (k, v))
                inventory.write('\n')
        job_name = gearman_job.name.split(':')[1]
        jjb_job = self.jobs[job_name]
        with open(jobdir.playbook, 'w') as playbook:
            tasks = []
            for builder in jjb_job.get('builders', []):
                if 'shell' in builder:
                    script_fn = '%s.sh' % str(uuid.uuid4().hex)
                    script_fn = os.path.join(jobdir.script_root, script_fn)
                    with open(script_fn, 'w') as script:
                        script.write(builder['shell'])
                    tasks.append(dict(script='%s >> /tmp/console.log 2>&1' %
                                      script_fn))
            play = dict(hosts='node', name='Job body',
                        tasks=tasks)
            playbook.write(yaml.dump([play]))
        with open(jobdir.config, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % jobdir.inventory)
            config.write('host_key_checking = False\n')

    def runAnsible(self, jobdir):
        self.ansible_proc = subprocess.Popen(
            ['ansible-playbook', jobdir.playbook],
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (out, err) = self.ansible_proc.communicate()
        ret = self.ansible_proc.wait()
        self.ansible_proc = None
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
