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

############################################################################
# NOTE(jhesketh): This file has been superceeded by zuul/launcher/server.py.
# It is kept here to make merging master back into v3 easier. Once closer
# to completion it can be removed.
############################################################################


import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import Queue

import gear
import jenkins_jobs.builder
import jenkins_jobs.formatter
import zmq

import zuul.ansible.library
from zuul.lib import commandsocket
from zuul.lib import yamlutil as yaml

ANSIBLE_WATCHDOG_GRACE = 5 * 60
ANSIBLE_DEFAULT_TIMEOUT = 2 * 60 * 60
ANSIBLE_DEFAULT_PRE_TIMEOUT = 10 * 60
ANSIBLE_DEFAULT_POST_TIMEOUT = 30 * 60


COMMANDS = ['reconfigure', 'stop', 'pause', 'unpause', 'release', 'graceful',
            'verbose', 'unverbose']


def boolify(x):
    if isinstance(x, str):
        return bool(int(x))
    return bool(x)


class LaunchGearWorker(gear.TextWorker):
    def __init__(self, *args, **kw):
        self.__launch_server = kw.pop('launch_server')
        super(LaunchGearWorker, self).__init__(*args, **kw)

    def handleNoop(self, packet):
        workers = len(self.__launch_server.node_workers)
        delay = (workers ** 2) / 1000.0
        time.sleep(delay)
        return super(LaunchGearWorker, self).handleNoop(packet)


class NodeGearWorker(gear.TextWorker):
    MASS_DO = 101

    def sendMassDo(self, functions):
        names = [gear.convert_to_bytes(x) for x in functions]
        data = b'\x00'.join(names)
        new_function_dict = {}
        for name in names:
            new_function_dict[name] = gear.FunctionRecord(name)
        self.broadcast_lock.acquire()
        try:
            p = gear.Packet(gear.constants.REQ, self.MASS_DO, data)
            self.broadcast(p)
            self.functions = new_function_dict
        finally:
            self.broadcast_lock.release()


class Watchdog(object):
    def __init__(self, timeout, function, args):
        self.timeout = timeout
        self.function = function
        self.args = args
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def _run(self):
        while self._running and time.time() < self.end:
            time.sleep(10)
        if self._running:
            self.function(*self.args)

    def start(self):
        self._running = True
        self.end = time.time() + self.timeout
        self.thread.start()

    def stop(self):
        self._running = False


class JobDir(object):
    def __init__(self, keep=False):
        self.keep = keep
        self.root = tempfile.mkdtemp()
        self.ansible_root = os.path.join(self.root, 'ansible')
        os.makedirs(self.ansible_root)
        self.known_hosts = os.path.join(self.ansible_root, 'known_hosts')
        self.inventory = os.path.join(self.ansible_root, 'inventory')
        self.vars = os.path.join(self.ansible_root, 'vars.yaml')
        self.pre_playbook = os.path.join(self.ansible_root, 'pre_playbook')
        self.playbook = os.path.join(self.ansible_root, 'playbook')
        self.post_playbook = os.path.join(self.ansible_root, 'post_playbook')
        self.config = os.path.join(self.ansible_root, 'ansible.cfg')
        self.pre_post_config = os.path.join(self.ansible_root,
                                            'ansible_pre_post.cfg')
        self.script_root = os.path.join(self.ansible_root, 'scripts')
        self.ansible_log = os.path.join(self.ansible_root, 'ansible_log.txt')
        os.makedirs(self.script_root)
        self.staging_root = os.path.join(self.root, 'staging')
        os.makedirs(self.staging_root)

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if not self.keep:
            shutil.rmtree(self.root)


class LaunchServer(object):
    log = logging.getLogger("zuul.LaunchServer")
    site_section_re = re.compile('site "(.*?)"')
    node_section_re = re.compile('node "(.*?)"')

    def __init__(self, config, keep_jobdir=False):
        self.config = config
        self.options = dict(
            verbose=False
        )
        self.keep_jobdir = keep_jobdir
        self.hostname = socket.gethostname()
        self.registered_functions = set()
        self.node_workers = {}
        self.jobs = {}
        self.builds = {}
        self.zmq_send_queue = Queue.Queue()
        self.termination_queue = Queue.Queue()
        self.sites = {}
        self.static_nodes = {}
        self.command_map = dict(
            reconfigure=self.reconfigure,
            stop=self.stop,
            pause=self.pause,
            unpause=self.unpause,
            release=self.release,
            graceful=self.graceful,
            verbose=self.verboseOn,
            unverbose=self.verboseOff,
        )

        if config.has_option('launcher', 'accept_nodes'):
            self.accept_nodes = config.getboolean('launcher',
                                                  'accept_nodes')
        else:
            self.accept_nodes = True
        self.config_accept_nodes = self.accept_nodes

        if self.config.has_option('zuul', 'state_dir'):
            state_dir = os.path.expanduser(
                self.config.get('zuul', 'state_dir'))
        else:
            state_dir = '/var/lib/zuul'
        path = os.path.join(state_dir, 'launcher.socket')
        self.command_socket = commandsocket.CommandSocket(path)
        ansible_dir = os.path.join(state_dir, 'ansible')
        self.library_dir = os.path.join(ansible_dir, 'library')
        if not os.path.exists(self.library_dir):
            os.makedirs(self.library_dir)
        self.pre_post_library_dir = os.path.join(ansible_dir,
                                                 'pre_post_library')
        if not os.path.exists(self.pre_post_library_dir):
            os.makedirs(self.pre_post_library_dir)

        library_path = os.path.dirname(os.path.abspath(
            zuul.ansible.library.__file__))
        # Ansible library modules that should be available to all
        # playbooks:
        all_libs = ['zuul_log.py', 'zuul_console.py', 'zuul_afs.py']
        # Modules that should only be used by job playbooks:
        job_libs = ['command.py']

        for fn in all_libs:
            shutil.copy(os.path.join(library_path, fn), self.library_dir)
            shutil.copy(os.path.join(library_path, fn),
                        self.pre_post_library_dir)
        for fn in job_libs:
            shutil.copy(os.path.join(library_path, fn), self.library_dir)

        def get_config_default(section, option, default):
            if config.has_option(section, option):
                return config.get(section, option)
            return default

        for section in config.sections():
            m = self.site_section_re.match(section)
            if m:
                sitename = m.group(1)
                d = {}
                d['host'] = get_config_default(section, 'host', None)
                d['user'] = get_config_default(section, 'user', '')
                d['pass'] = get_config_default(section, 'pass', '')
                d['root'] = get_config_default(section, 'root', '/')
                d['keytab'] = get_config_default(section, 'keytab', None)
                self.sites[sitename] = d
                continue
            m = self.node_section_re.match(section)
            if m:
                nodename = m.group(1)
                d = {}
                d['name'] = nodename
                d['host'] = config.get(section, 'host')
                d['description'] = get_config_default(section,
                                                      'description', '')
                if config.has_option(section, 'labels'):
                    d['labels'] = config.get(section, 'labels').split(',')
                else:
                    d['labels'] = []
                self.static_nodes[nodename] = d
                continue

    def start(self):
        self._gearman_running = True
        self._zmq_running = True
        self._reaper_running = True
        self._command_running = True

        # Setup ZMQ
        self.zcontext = zmq.Context()
        self.zsocket = self.zcontext.socket(zmq.PUB)
        self.zsocket.bind("tcp://*:8888")

        # Setup Gearman
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.worker = LaunchGearWorker('Zuul Launch Server',
                                       launch_server=self)
        self.worker.addServer(server, port)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.log.debug("Registering")
        self.register()

        # Start command socket
        self.log.debug("Starting command processor")
        self.command_socket.start()
        self.command_thread = threading.Thread(target=self.runCommand)
        self.command_thread.daemon = True
        self.command_thread.start()

        # Load JJB config
        self.loadJobs()

        # Start ZMQ worker thread
        self.log.debug("Starting ZMQ processor")
        self.zmq_thread = threading.Thread(target=self.runZMQ)
        self.zmq_thread.daemon = True
        self.zmq_thread.start()

        # Start node worker reaper thread
        self.log.debug("Starting reaper")
        self.reaper_thread = threading.Thread(target=self.runReaper)
        self.reaper_thread.daemon = True
        self.reaper_thread.start()

        # Start Gearman worker thread
        self.log.debug("Starting worker")
        self.gearman_thread = threading.Thread(target=self.run)
        self.gearman_thread.daemon = True
        self.gearman_thread.start()

        # Start static workers
        for node in self.static_nodes.values():
            self.log.debug("Creating static node with arguments: %s" % (node,))
            self._launchWorker(node)

    def loadJobs(self):
        self.log.debug("Loading jobs")
        builder = JJB()
        path = self.config.get('launcher', 'jenkins_jobs')
        builder.load_files([path])
        builder.parser.expandYaml()
        unseen = set(self.jobs.keys())
        for job in builder.parser.jobs:
            builder.expandMacros(job)
            self.jobs[job['name']] = job
            unseen.discard(job['name'])
        for name in unseen:
            del self.jobs[name]

    def register(self):
        new_functions = set()
        if self.accept_nodes:
            new_functions.add("node_assign:zuul")
        new_functions.add("stop:%s" % self.hostname)
        new_functions.add("set_description:%s" % self.hostname)
        new_functions.add("node_revoke:%s" % self.hostname)

        for function in new_functions - self.registered_functions:
            self.worker.registerFunction(function)
        for function in self.registered_functions - new_functions:
            self.worker.unRegisterFunction(function)
        self.registered_functions = new_functions

    def reconfigure(self):
        self.log.debug("Reconfiguring")
        self.loadJobs()
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.queue.put(dict(action='reconfigure'))
            except Exception:
                self.log.exception("Exception sending reconfigure command "
                                   "to worker:")
        self.log.debug("Reconfiguration complete")

    def pause(self):
        self.log.debug("Pausing")
        self.accept_nodes = False
        self.register()
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.queue.put(dict(action='pause'))
            except Exception:
                self.log.exception("Exception sending pause command "
                                   "to worker:")
        self.log.debug("Paused")

    def unpause(self):
        self.log.debug("Unpausing")
        self.accept_nodes = self.config_accept_nodes
        self.register()
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.queue.put(dict(action='unpause'))
            except Exception:
                self.log.exception("Exception sending unpause command "
                                   "to worker:")
        self.log.debug("Unpaused")

    def release(self):
        self.log.debug("Releasing idle nodes")
        for node in self.node_workers.values():
            if node.name in self.static_nodes:
                continue
            try:
                if node.isAlive():
                    node.queue.put(dict(action='release'))
            except Exception:
                self.log.exception("Exception sending release command "
                                   "to worker:")
        self.log.debug("Finished releasing idle nodes")

    def graceful(self):
        # Note: this is run in the command processing thread; no more
        # external commands will be processed after this.
        self.log.debug("Gracefully stopping")
        self.pause()
        self.release()
        self.log.debug("Waiting for all builds to finish")
        while self.builds:
            time.sleep(5)
        self.log.debug("All builds are finished")
        self.stop()

    def stop(self):
        self.log.debug("Stopping")
        # First, stop accepting new jobs
        self._gearman_running = False
        self._reaper_running = False
        self.worker.shutdown()
        # Then stop all of the workers
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.stop()
            except Exception:
                self.log.exception("Exception sending stop command to worker:")
        # Stop ZMQ afterwords so that the send queue is flushed
        self._zmq_running = False
        self.zmq_send_queue.put(None)
        self.zmq_send_queue.join()
        # Stop command processing
        self._command_running = False
        self.command_socket.stop()
        # Join the gearman thread which was stopped earlier.
        self.gearman_thread.join()
        # The command thread is joined in the join() method of this
        # class, which is called by the command shell.
        self.log.debug("Stopped")

    def verboseOn(self):
        self.log.debug("Enabling verbose mode")
        self.options['verbose'] = True

    def verboseOff(self):
        self.log.debug("Disabling verbose mode")
        self.options['verbose'] = False

    def join(self):
        self.command_thread.join()

    def runCommand(self):
        while self._command_running:
            try:
                command = self.command_socket.get()
                self.command_map[command]()
            except Exception:
                self.log.exception("Exception while processing command")

    def runZMQ(self):
        while self._zmq_running or not self.zmq_send_queue.empty():
            try:
                item = self.zmq_send_queue.get()
                self.log.debug("Got ZMQ event %s" % (item,))
                if item is None:
                    continue
                self.zsocket.send(item)
            except Exception:
                self.log.exception("Exception while processing ZMQ events")
            finally:
                self.zmq_send_queue.task_done()

    def run(self):
        while self._gearman_running:
            try:
                job = self.worker.getJob()
                try:
                    if job.name.startswith('node_assign:'):
                        self.log.debug("Got node_assign job: %s" % job.unique)
                        self.assignNode(job)
                    elif job.name.startswith('stop:'):
                        self.log.debug("Got stop job: %s" % job.unique)
                        self.stopJob(job)
                    elif job.name.startswith('set_description:'):
                        self.log.debug("Got set_description job: %s" %
                                       job.unique)
                        job.sendWorkComplete()
                    elif job.name.startswith('node_revoke:'):
                        self.log.debug("Got node_revoke job: %s" % job.unique)
                        self.revokeNode(job)
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
        self._launchWorker(args)
        data = dict(manager=self.hostname)
        job.sendWorkData(json.dumps(data))
        job.sendWorkComplete()

    def _launchWorker(self, args):
        worker = NodeWorker(self.config, self.jobs, self.builds,
                            self.sites, args['name'], args['host'],
                            args['description'], args['labels'],
                            self.hostname, self.zmq_send_queue,
                            self.termination_queue, self.keep_jobdir,
                            self.library_dir, self.pre_post_library_dir,
                            self.options)
        self.node_workers[worker.name] = worker

        worker.thread = threading.Thread(target=worker.run)
        worker.thread.start()

    def revokeNode(self, job):
        try:
            args = json.loads(job.arguments)
            self.log.debug("Revoke job with arguments: %s" % (args,))
            name = args['name']
            node = self.node_workers.get(name)
            if not node:
                self.log.debug("Unable to find worker %s" % (name,))
                return
            try:
                if node.isAlive():
                    node.queue.put(dict(action='stop'))
                else:
                    self.log.debug("Node %s is not alive while revoking node" %
                                   (node.name,))
            except Exception:
                self.log.exception("Exception sending stop command "
                                   "to worker:")
        finally:
            job.sendWorkComplete()

    def stopJob(self, job):
        try:
            args = json.loads(job.arguments)
            self.log.debug("Stop job with arguments: %s" % (args,))
            unique = args['number']
            build_worker_name = self.builds.get(unique)
            if not build_worker_name:
                self.log.debug("Unable to find build for job %s" % (unique,))
                return
            node = self.node_workers.get(build_worker_name)
            if not node:
                self.log.debug("Unable to find worker for job %s" % (unique,))
                return
            try:
                if node.isAlive():
                    node.queue.put(dict(action='abort'))
                else:
                    self.log.debug("Node %s is not alive while aborting job" %
                                   (node.name,))
            except Exception:
                self.log.exception("Exception sending abort command "
                                   "to worker:")
        finally:
            job.sendWorkComplete()

    def runReaper(self):
        # We don't actually care if all the events are processed
        while self._reaper_running:
            try:
                item = self.termination_queue.get()
                self.log.debug("Got termination event %s" % (item,))
                if item is None:
                    continue
                worker = self.node_workers[item]
                self.log.debug("Joining %s" % (item,))
                worker.thread.join()
                self.log.debug("Joined %s" % (item,))
                del self.node_workers[item]
            except Exception:
                self.log.exception("Exception while processing "
                                   "termination events:")
            finally:
                self.termination_queue.task_done()


class NodeWorker(object):
    retry_args = dict(register='task_result',
                      until='task_result.rc == 0',
                      retries=3,
                      delay=30)

    def __init__(self, config, jobs, builds, sites, name, host,
                 description, labels, manager_name, zmq_send_queue,
                 termination_queue, keep_jobdir, library_dir,
                 pre_post_library_dir, options):
        self.log = logging.getLogger("zuul.NodeWorker.%s" % (name,))
        self.log.debug("Creating node worker %s" % (name,))
        self.config = config
        self.jobs = jobs
        self.builds = builds
        self.sites = sites
        self.name = name
        self.host = host
        self.description = description
        if not isinstance(labels, list):
            labels = [labels]
        self.labels = labels
        self.thread = None
        self.registered_functions = set()
        # If the unpaused Event is set, that means we should run jobs.
        # If it is clear, then we are paused and should not run jobs.
        self.unpaused = threading.Event()
        self.unpaused.set()
        self._running = True
        self.queue = Queue.Queue()
        self.manager_name = manager_name
        self.zmq_send_queue = zmq_send_queue
        self.termination_queue = termination_queue
        self.keep_jobdir = keep_jobdir
        self.running_job_lock = threading.Lock()
        self.pending_registration = False
        self.registration_lock = threading.Lock()
        self._get_job_lock = threading.Lock()
        self._got_job = False
        self._job_complete_event = threading.Event()
        self._running_job = False
        self._aborted_job = False
        self._watchdog_timeout = False
        self._sent_complete_event = False
        self.ansible_pre_proc = None
        self.ansible_job_proc = None
        self.ansible_post_proc = None
        self.workspace_root = config.get('launcher', 'workspace_root')
        if self.config.has_option('launcher', 'private_key_file'):
            self.private_key_file = config.get('launcher', 'private_key_file')
        else:
            self.private_key_file = '~/.ssh/id_rsa'
        if self.config.has_option('launcher', 'username'):
            self.username = config.get('launcher', 'username')
        else:
            self.username = 'zuul'
        self.library_dir = library_dir
        self.pre_post_library_dir = pre_post_library_dir
        self.options = options

    def isAlive(self):
        # Meant to be called from the manager
        if self.thread and self.thread.is_alive():
            return True
        return False

    def run(self):
        self.log.debug("Node worker %s starting" % (self.name,))
        server = self.config.get('gearman', 'server')
        if self.config.has_option('gearman', 'port'):
            port = self.config.get('gearman', 'port')
        else:
            port = 4730
        self.worker = NodeGearWorker(self.name)
        self.worker.addServer(server, port)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.log.debug("Registering")
        self.register()

        self.gearman_thread = threading.Thread(target=self.runGearman)
        self.gearman_thread.daemon = True
        self.gearman_thread.start()

        self.log.debug("Started")

        while self._running or not self.queue.empty():
            try:
                self._runQueue()
            except Exception:
                self.log.exception("Exception in queue manager:")

    def stop(self):
        # If this is called locally, setting _running will be
        # effictive, if it's called remotely, it will not be, but it
        # will be set by the queue thread.
        self.log.debug("Submitting stop request")
        self._running = False
        self.unpaused.set()
        self.queue.put(dict(action='stop'))
        self.queue.join()

    def pause(self):
        self.unpaused.clear()
        self.worker.stopWaitingForJobs()

    def unpause(self):
        self.unpaused.set()

    def release(self):
        # If this node is idle, stop it.
        old_unpaused = self.unpaused.is_set()
        if old_unpaused:
            self.pause()
        with self._get_job_lock:
            if self._got_job:
                self.log.debug("This worker is not idle")
                if old_unpaused:
                    self.unpause()
                return
        self.log.debug("Stopping due to release command")
        self.queue.put(dict(action='stop'))

    def _runQueue(self):
        item = self.queue.get()
        try:
            if item['action'] == 'stop':
                self.log.debug("Received stop request")
                self._running = False
                self.termination_queue.put(self.name)
                if not self.abortRunningJob():
                    self.sendFakeCompleteEvent()
                else:
                    self._job_complete_event.wait()
                self.worker.shutdown()
            if item['action'] == 'pause':
                self.log.debug("Received pause request")
                self.pause()
            if item['action'] == 'unpause':
                self.log.debug("Received unpause request")
                self.unpause()
            if item['action'] == 'release':
                self.log.debug("Received release request")
                self.release()
            elif item['action'] == 'reconfigure':
                self.log.debug("Received reconfigure request")
                self.register()
            elif item['action'] == 'abort':
                self.log.debug("Received abort request")
                self.abortRunningJob()
        finally:
            self.queue.task_done()

    def runGearman(self):
        while self._running:
            try:
                self.unpaused.wait()
                if self._running:
                    self._runGearman()
            except Exception:
                self.log.exception("Exception in gearman manager:")
            with self._get_job_lock:
                self._got_job = False

    def _runGearman(self):
        if self.pending_registration:
            self.register()
        with self._get_job_lock:
            try:
                job = self.worker.getJob()
                self._got_job = True
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
        if not self.registration_lock.acquire(False):
            self.log.debug("Registration already in progress")
            return
        try:
            if self._running_job:
                self.pending_registration = True
                self.log.debug("Ignoring registration due to running job")
                return
            self.log.debug("Updating registration")
            self.pending_registration = False
            new_functions = set()
            for job in self.jobs.values():
                new_functions |= self.generateFunctionNames(job)
            self.worker.sendMassDo(new_functions)
            self.registered_functions = new_functions
        finally:
            self.registration_lock.release()

    def abortRunningJob(self):
        self._aborted_job = True
        return self.abortRunningProc(self.ansible_job_proc)

    def abortRunningProc(self, proc):
        aborted = False
        self.log.debug("Abort: acquiring job lock")
        with self.running_job_lock:
            if self._running_job:
                self.log.debug("Abort: a job is running")
                if proc:
                    self.log.debug("Abort: sending kill signal to job "
                                   "process group")
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                        aborted = True
                    except Exception:
                        self.log.exception("Exception while killing "
                                           "ansible process:")
            else:
                self.log.debug("Abort: no job is running")

        return aborted

    def launch(self, job):
        self.log.info("Node worker %s launching job %s" %
                      (self.name, job.name))

        # Make sure we can parse what we need from the job first
        args = json.loads(job.arguments)
        offline = boolify(args.get('OFFLINE_NODE_WHEN_COMPLETE', False))
        job_name = job.name.split(':')[1]

        # Initialize the result so we have something regardless of
        # whether the job actually runs
        result = None
        self._sent_complete_event = False
        self._aborted_job = False
        self._watchdog_timeout = False

        try:
            self.sendStartEvent(job_name, args)
        except Exception:
            self.log.exception("Exception while sending job start event")

        try:
            result = self.runJob(job, args)
        except Exception:
            self.log.exception("Exception while launching job thread")

        self._running_job = False

        try:
            data = json.dumps(dict(result=result))
            job.sendWorkComplete(data)
        except Exception:
            self.log.exception("Exception while sending job completion packet")

        try:
            self.sendCompleteEvent(job_name, result, args)
        except Exception:
            self.log.exception("Exception while sending job completion event")

        try:
            del self.builds[job.unique]
        except Exception:
            self.log.exception("Exception while clearing build record")

        self._job_complete_event.set()
        if offline and self._running:
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

    def runJob(self, job, args):
        self.ansible_pre_proc = None
        self.ansible_job_proc = None
        self.ansible_post_proc = None
        result = None
        with self.running_job_lock:
            if not self._running:
                return result
            self._running_job = True
            self._job_complete_event.clear()

        self.log.debug("Job %s: beginning" % (job.unique,))
        self.builds[job.unique] = self.name
        with JobDir(self.keep_jobdir) as jobdir:
            self.log.debug("Job %s: job root at %s" %
                           (job.unique, jobdir.root))
            timeout = self.prepareAnsibleFiles(jobdir, job, args)

            data = {
                'manager': self.manager_name,
                'number': job.unique,
            }
            if ':' in self.host:
                data['url'] = 'telnet://[%s]:19885' % self.host
            else:
                data['url'] = 'telnet://%s:19885' % self.host

            job.sendWorkData(json.dumps(data))
            job.sendWorkStatus(0, 100)

            pre_status = self.runAnsiblePrePlaybook(jobdir)
            if pre_status is None:
                # These should really never fail, so return None and have
                # zuul try again
                return result

            job_status = self.runAnsiblePlaybook(jobdir, timeout)
            if job_status is None:
                # The result of the job is indeterminate.  Zuul will
                # run it again.
                return result

            post_status = self.runAnsiblePostPlaybook(jobdir, job_status)
            if not post_status:
                result = 'POST_FAILURE'
            elif job_status:
                result = 'SUCCESS'
            else:
                result = 'FAILURE'

            if self._aborted_job and not self._watchdog_timeout:
                # A Null result will cause zuul to relaunch the job if
                # it needs to.
                result = None

        return result

    def getHostList(self):
        return [('node', dict(
            ansible_host=self.host, ansible_user=self.username))]

    def _substituteVariables(self, text, variables):
        def lookup(match):
            return variables.get(match.group(1), '')
        return re.sub('\$([A-Za-z0-9_]+)', lookup, text)

    def _getRsyncOptions(self, source, parameters):
        # Treat the publisher source as a filter; ant and rsync behave
        # fairly close in this manner, except for leading directories.
        source = self._substituteVariables(source, parameters)
        # If the source starts with ** then we want to match any
        # number of directories, so don't anchor the include filter.
        # If it does not start with **, then the intent is likely to
        # at least start by matching an immediate file or subdirectory
        # (even if later we have a ** in the middle), so in this case,
        # anchor it to the root of the transfer (the workspace).
        if not source.startswith('**'):
            source = os.path.join('/', source)
        # These options mean: include the thing we want, include any
        # directories (so that we continue to search for the thing we
        # want no matter how deep it is), exclude anything that
        # doesn't match the thing we want or is a directory, then get
        # rid of empty directories left over at the end.
        rsync_opts = ['--include="%s"' % source,
                      '--include="*/"',
                      '--exclude="*"',
                      '--prune-empty-dirs']
        return rsync_opts

    def _makeSCPTask(self, jobdir, publisher, parameters):
        tasks = []
        for scpfile in publisher['scp']['files']:
            scproot = tempfile.mkdtemp(dir=jobdir.staging_root)
            os.chmod(scproot, 0o755)

            site = publisher['scp']['site']
            if scpfile.get('copy-console'):
                # Include the local ansible directory in the console
                # upload.  This uploads the playbook and ansible logs.
                copyargs = dict(src=jobdir.ansible_root + '/',
                                dest=os.path.join(scproot, '_zuul_ansible'))
                task = dict(name='copy console log',
                            copy=copyargs,
                            delegate_to='127.0.0.1')
                # This is a local copy and should not fail, so does
                # not need a retry stanza.
                tasks.append(task)

                # Fetch the console log from the remote host.
                src = '/tmp/console.html'
                rsync_opts = []
            else:
                src = parameters['WORKSPACE']
                if not src.endswith('/'):
                    src = src + '/'
                rsync_opts = self._getRsyncOptions(scpfile['source'],
                                                   parameters)

            syncargs = dict(src=src,
                            dest=scproot,
                            copy_links='yes',
                            mode='pull')
            if rsync_opts:
                syncargs['rsync_opts'] = rsync_opts
            task = dict(name='copy files from node',
                        synchronize=syncargs)
            if not scpfile.get('copy-after-failure'):
                task['when'] = 'success|bool'
            # We don't use retry_args here because there is a bug in
            # the synchronize module that breaks subsequent attempts at
            # retrying. Better to try once and get an accurate error
            # message if it fails.
            # https://github.com/ansible/ansible/issues/18281
            tasks.append(task)

            task = self._makeSCPTaskLocalAction(
                site, scpfile, scproot, parameters)
            task.update(self.retry_args)
            tasks.append(task)
        return tasks

    def _makeSCPTaskLocalAction(self, site, scpfile, scproot, parameters):
        if site not in self.sites:
            raise Exception("Undefined SCP site: %s" % (site,))
        site = self.sites[site]
        dest = scpfile['target'].lstrip('/')
        dest = self._substituteVariables(dest, parameters)
        dest = os.path.join(site['root'], dest)
        dest = os.path.normpath(dest)
        if not dest.startswith(site['root']):
            raise Exception("Target path %s is not below site root" %
                            (dest,))

        rsync_cmd = [
            '/usr/bin/rsync', '--delay-updates', '-F',
            '--compress', '-rt', '--safe-links',
            '--rsync-path="mkdir -p {dest} && rsync"',
            '--rsh="/usr/bin/ssh -i {private_key_file} -S none '
            '-o StrictHostKeyChecking=no -q"',
            '--out-format="<<CHANGED>>%i %n%L"',
            '{source}', '"{user}@{host}:{dest}"'
        ]
        if scpfile.get('keep-hierarchy'):
            source = '"%s/"' % scproot
        else:
            source = '`/usr/bin/find "%s" -type f`' % scproot
        shellargs = ' '.join(rsync_cmd).format(
            source=source,
            dest=dest,
            private_key_file=self.private_key_file,
            host=site['host'],
            user=site['user'])
        task = dict(name='rsync logs to server',
                    shell=shellargs,
                    delegate_to='127.0.0.1')
        if not scpfile.get('copy-after-failure'):
            task['when'] = 'success|bool'

        return task

    def _makeFTPTask(self, jobdir, publisher, parameters):
        tasks = []
        ftp = publisher['ftp']
        site = ftp['site']
        if site not in self.sites:
            raise Exception("Undefined FTP site: %s" % site)
        site = self.sites[site]

        ftproot = tempfile.mkdtemp(dir=jobdir.staging_root)
        ftpcontent = os.path.join(ftproot, 'content')
        os.makedirs(ftpcontent)
        ftpscript = os.path.join(ftproot, 'script')

        src = parameters['WORKSPACE']
        if not src.endswith('/'):
            src = src + '/'
        rsync_opts = self._getRsyncOptions(ftp['source'],
                                           parameters)
        syncargs = dict(src=src,
                        dest=ftpcontent,
                        copy_links='yes',
                        mode='pull')
        if rsync_opts:
            syncargs['rsync_opts'] = rsync_opts
        task = dict(name='copy files from node',
                    synchronize=syncargs,
                    when='success|bool')
        # We don't use retry_args here because there is a bug in the
        # synchronize module that breaks subsequent attempts at retrying.
        # Better to try once and get an accurate error message if it fails.
        # https://github.com/ansible/ansible/issues/18281
        tasks.append(task)
        task = dict(name='FTP files to server',
                    shell='lftp -f %s' % ftpscript,
                    when='success|bool',
                    delegate_to='127.0.0.1')
        ftpsource = ftpcontent
        if ftp.get('remove-prefix'):
            ftpsource = os.path.join(ftpcontent, ftp['remove-prefix'])
        while ftpsource[-1] == '/':
            ftpsource = ftpsource[:-1]
        ftptarget = ftp['target'].lstrip('/')
        ftptarget = self._substituteVariables(ftptarget, parameters)
        ftptarget = os.path.join(site['root'], ftptarget)
        ftptarget = os.path.normpath(ftptarget)
        if not ftptarget.startswith(site['root']):
            raise Exception("Target path %s is not below site root" %
                            (ftptarget,))
        while ftptarget[-1] == '/':
            ftptarget = ftptarget[:-1]
        with open(ftpscript, 'w') as script:
            script.write('open %s\n' % site['host'])
            script.write('user %s %s\n' % (site['user'], site['pass']))
            script.write('mirror -R %s %s\n' % (ftpsource, ftptarget))
        task.update(self.retry_args)
        tasks.append(task)
        return tasks

    def _makeAFSTask(self, jobdir, publisher, parameters):
        tasks = []
        afs = publisher['afs']
        site = afs['site']
        if site not in self.sites:
            raise Exception("Undefined AFS site: %s" % site)
        site = self.sites[site]

        afsroot = tempfile.mkdtemp(dir=jobdir.staging_root)
        afscontent = os.path.join(afsroot, 'content')
        afssource = afscontent
        if afs.get('remove-prefix'):
            afssource = os.path.join(afscontent, afs['remove-prefix'])
        while afssource[-1] == '/':
            afssource = afssource[:-1]

        src = parameters['WORKSPACE']
        if not src.endswith('/'):
            src = src + '/'
        rsync_opts = self._getRsyncOptions(afs['source'],
                                           parameters)
        syncargs = dict(src=src,
                        dest=afscontent,
                        copy_links='yes',
                        mode='pull')
        if rsync_opts:
            syncargs['rsync_opts'] = rsync_opts
        task = dict(name='copy files from node',
                    synchronize=syncargs,
                    when='success|bool')
        # We don't use retry_args here because there is a bug in the
        # synchronize module that breaks subsequent attempts at retrying.
        # Better to try once and get an accurate error message if it fails.
        # https://github.com/ansible/ansible/issues/18281
        tasks.append(task)

        afstarget = afs['target'].lstrip('/')
        afstarget = self._substituteVariables(afstarget, parameters)
        afstarget = os.path.join(site['root'], afstarget)
        afstarget = os.path.normpath(afstarget)
        if not afstarget.startswith(site['root']):
            raise Exception("Target path %s is not below site root" %
                            (afstarget,))

        afsargs = dict(user=site['user'],
                       keytab=site['keytab'],
                       root=afsroot,
                       source=afssource,
                       target=afstarget)

        task = dict(name='Synchronize files to AFS',
                    zuul_afs=afsargs,
                    when='success|bool',
                    delegate_to='127.0.0.1')
        tasks.append(task)

        return tasks

    def _makeBuilderTask(self, jobdir, builder, parameters, sequence):
        tasks = []
        script_fn = '%02d-%s.sh' % (sequence, str(uuid.uuid4().hex))
        script_path = os.path.join(jobdir.script_root, script_fn)
        with open(script_path, 'w') as script:
            data = builder['shell']
            if not data.startswith('#!'):
                data = '#!/bin/bash -x\n %s' % (data,)
            script.write(data)

        remote_path = os.path.join('/tmp', script_fn)
        copy = dict(src=script_path,
                    dest=remote_path,
                    mode=0o555)
        task = dict(copy=copy)
        tasks.append(task)

        task = dict(command=remote_path)
        task['name'] = 'command generated from JJB'
        task['environment'] = "{{ zuul.environment }}"
        task['args'] = dict(chdir=parameters['WORKSPACE'])
        tasks.append(task)

        filetask = dict(path=remote_path,
                        state='absent')
        task = dict(file=filetask)
        tasks.append(task)

        return tasks

    def _transformPublishers(self, jjb_job):
        early_publishers = []
        late_publishers = []
        old_publishers = jjb_job.get('publishers', [])
        for publisher in old_publishers:
            early_scpfiles = []
            late_scpfiles = []
            if 'scp' not in publisher:
                early_publishers.append(publisher)
                continue
            copy_console = False
            for scpfile in publisher['scp']['files']:
                if scpfile.get('copy-console'):
                    scpfile['keep-hierarchy'] = True
                    late_scpfiles.append(scpfile)
                    copy_console = True
                else:
                    early_scpfiles.append(scpfile)
            publisher['scp']['files'] = early_scpfiles + late_scpfiles
            if copy_console:
                late_publishers.append(publisher)
            else:
                early_publishers.append(publisher)
        publishers = early_publishers + late_publishers
        if old_publishers != publishers:
            self.log.debug("Transformed job publishers")
        return early_publishers, late_publishers

    def prepareAnsibleFiles(self, jobdir, gearman_job, args):
        job_name = gearman_job.name.split(':')[1]
        jjb_job = self.jobs[job_name]

        parameters = args.copy()
        parameters['WORKSPACE'] = os.path.join(self.workspace_root, job_name)

        with open(jobdir.inventory, 'w') as inventory:
            for host_name, host_vars in self.getHostList():
                inventory.write(host_name)
                for k, v in host_vars.items():
                    inventory.write(' %s=%s' % (k, v))
                inventory.write('\n')

        timeout = None
        timeout_var = None
        for wrapper in jjb_job.get('wrappers', []):
            if isinstance(wrapper, dict):
                build_timeout = wrapper.get('timeout')
                if isinstance(build_timeout, dict):
                    timeout_var = build_timeout.get('timeout-var')
                    timeout = build_timeout.get('timeout')
                    if timeout is not None:
                        timeout = int(timeout) * 60
        if not timeout:
            timeout = ANSIBLE_DEFAULT_TIMEOUT
        if timeout_var:
            parameters[timeout_var] = str(timeout * 1000)

        with open(jobdir.vars, 'w') as vars_yaml:
            variables = dict(
                timeout=timeout,
                environment=parameters,
            )
            zuul_vars = dict(zuul=variables)
            vars_yaml.write(
                yaml.safe_dump(zuul_vars, default_flow_style=False))

        with open(jobdir.pre_playbook, 'w') as pre_playbook:

            shellargs = "ssh-keyscan {{ ansible_host }} > %s" % (
                jobdir.known_hosts)
            tasks = []
            tasks.append(dict(shell=shellargs, delegate_to='127.0.0.1'))

            task = dict(file=dict(path='/tmp/console.html', state='absent'))
            tasks.append(task)

            task = dict(zuul_console=dict(path='/tmp/console.html',
                                          port=19885))
            tasks.append(task)

            task = dict(file=dict(path=parameters['WORKSPACE'],
                                  state='directory'))
            tasks.append(task)

            msg = [
                "Launched by %s" % self.manager_name,
                "Building remotely on %s in workspace %s" % (
                    self.name, parameters['WORKSPACE'])]
            task = dict(zuul_log=dict(msg=msg))
            tasks.append(task)

            play = dict(hosts='node', name='Job setup', tasks=tasks)
            pre_playbook.write(
                yaml.safe_dump([play], default_flow_style=False))

        with open(jobdir.playbook, 'w') as playbook:
            tasks = []

            sequence = 0
            for builder in jjb_job.get('builders', []):
                if 'shell' in builder:
                    sequence += 1
                    tasks.extend(
                        self._makeBuilderTask(jobdir, builder, parameters,
                                              sequence))

            play = dict(hosts='node', name='Job body', tasks=tasks)
            playbook.write(yaml.safe_dump([play], default_flow_style=False))

        early_publishers, late_publishers = self._transformPublishers(jjb_job)

        with open(jobdir.post_playbook, 'w') as playbook:
            blocks = []
            for publishers in [early_publishers, late_publishers]:
                block = []
                for publisher in publishers:
                    if 'scp' in publisher:
                        block.extend(self._makeSCPTask(jobdir, publisher,
                                                       parameters))
                    if 'ftp' in publisher:
                        block.extend(self._makeFTPTask(jobdir, publisher,
                                                       parameters))
                    if 'afs' in publisher:
                        block.extend(self._makeAFSTask(jobdir, publisher,
                                                       parameters))
                blocks.append(block)

            # The 'always' section contains the log publishing tasks,
            # the 'block' contains all the other publishers.  This way
            # we run the log publisher regardless of whether the rest
            # of the publishers succeed.
            tasks = []

            task = dict(zuul_log=dict(msg="Job complete, result: SUCCESS"),
                        when='success|bool')
            blocks[0].insert(0, task)
            task = dict(zuul_log=dict(msg="Job complete, result: FAILURE"),
                        when='not success|bool and not timedout|bool')
            blocks[0].insert(0, task)
            task = dict(zuul_log=dict(msg="Job timed out, result: FAILURE"),
                        when='not success|bool and timedout|bool')
            blocks[0].insert(0, task)

            tasks.append(dict(block=blocks[0],
                              always=blocks[1]))

            play = dict(hosts='node', name='Publishers',
                        tasks=tasks)
            playbook.write(yaml.safe_dump([play], default_flow_style=False))

        self._writeAnsibleConfig(jobdir, jobdir.config,
                                 library=self.library_dir)
        self._writeAnsibleConfig(jobdir, jobdir.pre_post_config,
                                 library=self.pre_post_library_dir)

        return timeout

    def _writeAnsibleConfig(self, jobdir, fn, library):
        with open(fn, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % jobdir.inventory)
            config.write('local_tmp = %s/.ansible/local_tmp\n' % jobdir.root)
            config.write('remote_tmp = %s/.ansible/remote_tmp\n' % jobdir.root)
            config.write('private_key_file = %s\n' % self.private_key_file)
            config.write('retry_files_enabled = False\n')
            config.write('log_path = %s\n' % jobdir.ansible_log)
            config.write('gathering = explicit\n')
            config.write('library = %s\n' % library)
            # TODO(mordred) This can be removed once we're using ansible 2.2
            config.write('module_set_locale = False\n')
            # bump the timeout because busy nodes may take more than
            # 10s to respond
            config.write('timeout = 30\n')

            config.write('[ssh_connection]\n')
            # NB: when setting pipelining = True, keep_remote_files
            # must be False (the default).  Otherwise it apparently
            # will override the pipelining option and effectively
            # disable it.  Pipelining has a side effect of running the
            # command without a tty (ie, without the -tt argument to
            # ssh).  We require this behavior so that if a job runs a
            # command which expects interactive input on a tty (such
            # as sudo) it does not hang.
            config.write('pipelining = True\n')
            ssh_args = "-o ControlMaster=auto -o ControlPersist=60s " \
                "-o UserKnownHostsFile=%s" % jobdir.known_hosts
            config.write('ssh_args = %s\n' % ssh_args)

    def _ansibleTimeout(self, proc, msg):
        self._watchdog_timeout = True
        self.log.warning(msg)
        self.abortRunningProc(proc)

    def runAnsiblePrePlaybook(self, jobdir):
        # Set LOGNAME env variable so Ansible log_path log reports
        # the correct user.
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'
        env_copy['ANSIBLE_CONFIG'] = jobdir.pre_post_config

        if self.options['verbose']:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', jobdir.pre_playbook,
               '-e@%s' % jobdir.vars, verbose]
        self.log.debug("Ansible pre command: %s" % (cmd,))

        self.ansible_pre_proc = subprocess.Popen(
            cmd,
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env_copy,
        )
        ret = None
        watchdog = Watchdog(ANSIBLE_DEFAULT_PRE_TIMEOUT,
                            self._ansibleTimeout,
                            (self.ansible_pre_proc,
                             "Ansible pre timeout exceeded"))
        watchdog.start()
        try:
            for line in iter(self.ansible_pre_proc.stdout.readline, b''):
                line = line[:1024].rstrip()
                self.log.debug("Ansible pre output: %s" % (line,))
            ret = self.ansible_pre_proc.wait()
        finally:
            watchdog.stop()
        self.log.debug("Ansible pre exit code: %s" % (ret,))
        self.ansible_pre_proc = None
        return ret == 0

    def runAnsiblePlaybook(self, jobdir, timeout):
        # Set LOGNAME env variable so Ansible log_path log reports
        # the correct user.
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'
        env_copy['ANSIBLE_CONFIG'] = jobdir.config

        if self.options['verbose']:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', jobdir.playbook, verbose,
               '-e@%s' % jobdir.vars]
        self.log.debug("Ansible command: %s" % (cmd,))

        self.ansible_job_proc = subprocess.Popen(
            cmd,
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env_copy,
        )
        ret = None
        watchdog = Watchdog(timeout + ANSIBLE_WATCHDOG_GRACE,
                            self._ansibleTimeout,
                            (self.ansible_job_proc,
                             "Ansible timeout exceeded"))
        watchdog.start()
        try:
            for line in iter(self.ansible_job_proc.stdout.readline, b''):
                line = line[:1024].rstrip()
                self.log.debug("Ansible output: %s" % (line,))
            ret = self.ansible_job_proc.wait()
        finally:
            watchdog.stop()
        self.log.debug("Ansible exit code: %s" % (ret,))
        self.ansible_job_proc = None
        if self._watchdog_timeout:
            return False
        if ret == 3:
            # AnsibleHostUnreachable: We had a network issue connecting to
            # our zuul-worker.
            return None
        elif ret == -9:
            # Received abort request.
            return None
        return ret == 0

    def runAnsiblePostPlaybook(self, jobdir, success):
        # Set LOGNAME env variable so Ansible log_path log reports
        # the correct user.
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'
        env_copy['ANSIBLE_CONFIG'] = jobdir.pre_post_config

        if self.options['verbose']:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', jobdir.post_playbook,
               '-e', 'success=%s' % success,
               '-e', 'timedout=%s' % self._watchdog_timeout,
               '-e@%s' % jobdir.vars,
               verbose]
        self.log.debug("Ansible post command: %s" % (cmd,))

        self.ansible_post_proc = subprocess.Popen(
            cmd,
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env_copy,
        )
        ret = None
        watchdog = Watchdog(ANSIBLE_DEFAULT_POST_TIMEOUT,
                            self._ansibleTimeout,
                            (self.ansible_post_proc,
                             "Ansible post timeout exceeded"))
        watchdog.start()
        try:
            for line in iter(self.ansible_post_proc.stdout.readline, b''):
                line = line[:1024].rstrip()
                self.log.debug("Ansible post output: %s" % (line,))
            ret = self.ansible_post_proc.wait()
        finally:
            watchdog.stop()
        self.log.debug("Ansible post exit code: %s" % (ret,))
        self.ansible_post_proc = None
        return ret == 0


class JJB(jenkins_jobs.builder.Builder):
    def __init__(self):
        self.global_config = None
        self._plugins_list = []

    def expandComponent(self, component_type, component, template_data):
        component_list_type = component_type + 's'
        new_components = []
        if isinstance(component, dict):
            name, component_data = next(iter(component.items()))
            if template_data:
                component_data = jenkins_jobs.formatter.deep_format(
                    component_data, template_data, True)
        else:
            name = component
            component_data = {}

        new_component = self.parser.data.get(component_type, {}).get(name)
        if new_component:
            for new_sub_component in new_component[component_list_type]:
                new_components.extend(
                    self.expandComponent(component_type,
                                         new_sub_component, component_data))
        else:
            new_components.append({name: component_data})
        return new_components

    def expandMacros(self, job):
        for component_type in ['builder', 'publisher', 'wrapper']:
            component_list_type = component_type + 's'
            new_components = []
            for new_component in job.get(component_list_type, []):
                new_components.extend(self.expandComponent(component_type,
                                                           new_component, {}))
            job[component_list_type] = new_components
