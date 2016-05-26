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
import re
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
import jenkins_jobs.formatter
import zmq

import zuul.ansible.library
import zuul.ansible.plugins.callback_plugins


class JobDir(object):
    def __init__(self, keep=False):
        self.keep = keep
        self.root = tempfile.mkdtemp()
        self.git_root = os.path.join(self.root, 'git')
        os.makedirs(self.git_root)
        self.ansible_root = os.path.join(self.root, 'ansible')
        os.makedirs(self.ansible_root)
        self.plugins_root = os.path.join(self.ansible_root, 'plugins')
        os.makedirs(self.plugins_root)
        self.inventory = os.path.join(self.ansible_root, 'inventory')
        self.playbook = os.path.join(self.ansible_root, 'playbook')
        self.post_playbook = os.path.join(self.ansible_root, 'post_playbook')
        self.config = os.path.join(self.ansible_root, 'ansible.cfg')
        self.script_root = os.path.join(self.ansible_root, 'scripts')
        os.makedirs(self.script_root)

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if not self.keep:
            shutil.rmtree(self.root)


class LaunchServer(object):
    log = logging.getLogger("zuul.LaunchServer")
    section_re = re.compile('site "(.*?)"')

    def __init__(self, config, keep_jobdir=False):
        self.config = config
        self.keep_jobdir = keep_jobdir
        self.hostname = socket.gethostname()
        self.node_workers = {}
        self.mpmanager = multiprocessing.Manager()
        self.jobs = self.mpmanager.dict()
        self.builds = self.mpmanager.dict()
        self.zmq_send_queue = multiprocessing.JoinableQueue()
        self.termination_queue = multiprocessing.JoinableQueue()
        self.sites = {}

        for section in config.sections():
            m = self.section_re.match(section)
            if m:
                sitename = m.group(1)
                d = {}
                d['host'] = config.get(section, 'host')
                d['user'] = config.get(section, 'user')
                d['pass'] = config.get(section, 'pass', '')
                d['root'] = config.get(section, 'root', '/')
                self.sites[sitename] = d

    def start(self):
        self._gearman_running = True
        self._zmq_running = True
        self._reaper_running = True

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
        self.worker.registerFunction("node-assign:zuul")
        self.worker.registerFunction("stop:%s" % self.hostname)

    def reconfigure(self, config):
        self.log.debug("Reconfiguring")
        self.config = config
        self.loadJobs()
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.queue.put(dict(action='reconfigure'))
            except Exception:
                self.log.exception("Exception sending reconfigure command "
                                   "to worker:")
        self.log.debug("Reconfiguration complete")

    def stop(self):
        self.log.debug("Stopping")
        self._gearman_running = False
        self._reaper_running = False
        self.worker.shutdown()
        for node in self.node_workers.values():
            try:
                if node.isAlive():
                    node.stop()
            except Exception:
                self.log.exception("Exception sending stop command to worker:")
        self._zmq_running = False
        self.zmq_send_queue.put(None)
        self.zmq_send_queue.join()
        self.log.debug("Stopped")

    def join(self):
        self.gearman_thread.join()

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
                    if job.name.startswith('node-assign:'):
                        self.log.debug("Got node-assign job: %s" % job.unique)
                        self.assignNode(job)
                    elif job.name.startswith('stop:'):
                        self.log.debug("Got stop job: %s" % job.unique)
                        self.stopJob(job)
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
        worker = NodeWorker(self.config, self.jobs, self.builds,
                            self.sites, args['name'], args['host'],
                            args['description'], args['labels'],
                            self.hostname, self.zmq_send_queue,
                            self.termination_queue, self.keep_jobdir)
        self.node_workers[worker.name] = worker

        worker.process = multiprocessing.Process(target=worker.run)
        worker.process.start()

        data = dict(manager=self.hostname)
        job.sendWorkData(json.dumps(data))
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
                worker.process.join()
                self.log.debug("Joined %s" % (item,))
                del self.node_workers[item]
            except Exception:
                self.log.exception("Exception while processing "
                                   "termination events:")
            finally:
                self.termination_queue.task_done()


class NodeWorker(object):
    def __init__(self, config, jobs, builds, sites, name, host,
                 description, labels, manager_name, zmq_send_queue,
                 termination_queue, keep_jobdir):
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
        self.process = None
        self.registered_functions = set()
        self._running = True
        self.queue = multiprocessing.JoinableQueue()
        self.manager_name = manager_name
        self.zmq_send_queue = zmq_send_queue
        self.termination_queue = termination_queue
        self.keep_jobdir = keep_jobdir
        self.running_job_lock = threading.Lock()
        self._job_complete_event = threading.Event()
        self._running_job = False
        self._sent_complete_event = False
        self.workspace_root = config.get('launcher', 'workspace_root')
        if self.config.has_option('launcher', 'private_key_file'):
            self.private_key_file = config.get('launcher', 'private_key_file')
        else:
            self.private_key_file = '~/.ssh/id_rsa'
        if self.config.has_option('launcher', 'username'):
            self.username = config.get('launcher', 'username')
        else:
            self.username = 'zuul'

    def isAlive(self):
        # Meant to be called from the manager
        if self.process and self.process.is_alive():
            return True
        return False

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
        self.queue.put(dict(action='stop'))
        self.queue.join()

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
                self._runGearman()
            except Exception:
                self.log.exception("Exception in gearman manager:")

    def _runGearman(self):
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
            result = self.runJob(job, args)
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
        self.ansible_proc = None
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
                'url': 'telnet://%s:8088' % self.host,
            }
            job.sendWorkData(json.dumps(data))
            job.sendWorkStatus(0, 100)

            job_status = self.runAnsiblePlaybook(jobdir, timeout)
            post_status = self.runAnsiblePostPlaybook(jobdir, job_status)
            if job_status and post_status:
                status = 'SUCCESS'
            else:
                status = 'FAILURE'

            result = json.dumps(dict(result=status))

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
            site = publisher['scp']['site']
            if site not in self.sites:
                raise Exception("Undefined SCP site: %s" % (site,))
            site = self.sites[site]
            if scpfile.get('copy-console'):
                src = '/tmp/console.html'
                rsync_opts = []
            else:
                src = parameters['WORKSPACE']
                if not src.endswith('/'):
                    src = src + '/'
                rsync_opts = self._getRsyncOptions(scpfile['source'],
                                                   parameters)

            scproot = tempfile.mkdtemp(dir=jobdir.ansible_root)
            os.chmod(scproot, 0o755)
            syncargs = dict(src=src,
                            dest=scproot,
                            copy_links='yes',
                            mode='pull')
            if rsync_opts:
                syncargs['rsync_opts'] = rsync_opts
            task = dict(synchronize=syncargs)
            if not scpfile.get('copy-after-failure'):
                task['when'] = 'success'
            tasks.append(task)

            dest = scpfile['target']
            dest = self._substituteVariables(dest, parameters)
            dest = os.path.join(site['root'], dest)
            dest = os.path.normpath(dest)
            if not dest.startswith(site['root']):
                raise Exception("Target path %s is not below site root" %
                                (dest,))

            local_args = [
                'command', '/usr/bin/rsync', '--delay-updates', '-F',
                '--compress', '-rt', '--safe-links',
                '--rsync-path="mkdir -p {dest} && rsync"',
                '--rsh="/usr/bin/ssh -i {private_key_file} -S none '
                '-o StrictHostKeyChecking=no -q"',
                '--out-format="<<CHANGED>>%i %n%L"',
                '"{source}/"', '"{user}@{host}:{dest}"'
            ]
            local_action = ' '.join(local_args).format(
                source=scproot,
                dest=dest,
                private_key_file=self.private_key_file,
                host=site['host'],
                user=site['user'])
            task = dict(local_action=local_action)
            if not scpfile.get('copy-after-failure'):
                task['when'] = 'success'
            tasks.append(task)
        return tasks

    def _makeFTPTask(self, jobdir, publisher, parameters):
        tasks = []
        ftp = publisher['ftp']
        site = ftp['site']
        if site not in self.sites:
            raise Exception("Undefined FTP site: %s" % site)
        site = self.sites[site]

        ftproot = tempfile.mkdtemp(dir=jobdir.ansible_root)
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
                        copy_links='yes')
        if rsync_opts:
            syncargs['rsync_opts'] = rsync_opts
        task = dict(synchronize=syncargs,
                    when='success')
        tasks.append(task)
        task = dict(shell='lftp -f %s' % ftpscript,
                    when='success')
        ftpsource = ftpcontent
        if ftp.get('remove-prefix'):
            ftpsource = os.path.join(ftpcontent, ftp['remove-prefix'])
        while ftpsource[-1] == '/':
            ftpsource = ftpsource[:-1]
        ftptarget = ftp['target']
        ftptarget = self._substituteVariables(ftptarget, parameters)
        ftptarget = os.path.join(site['root'], ftp['target'])
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
        tasks.append(task)
        return tasks

    def _makeBuilderTask(self, jobdir, builder, parameters, timeout):
        tasks = []
        script_fn = '%s.sh' % str(uuid.uuid4().hex)
        script_path = os.path.join(jobdir.script_root, script_fn)
        with open(script_path, 'w') as script:
            data = builder['shell']
            if not data.startswith('#!'):
                data = '#!/bin/bash -x\n %s' % (data,)
            script.write(data)

        remote_path = os.path.join('/tmp', script_fn)
        copy = dict(src=script_path,
                    dest=remote_path,
                    mode=0555)
        task = dict(copy=copy)
        tasks.append(task)

        runner = dict(command=remote_path,
                      cwd=parameters['WORKSPACE'],
                      parameters=parameters)
        task = dict(zuul_runner=runner)
        if timeout:
            task['when'] = '{{ timeout | int > 0 }}'
            task['async'] = '{{ timeout }}'
        else:
            task['async'] = 2 * 60 * 60  # 2 hour default timeout
        task['poll'] = 5
        tasks.append(task)

        filetask = dict(path=remote_path,
                        state='absent')
        task = dict(file=filetask)
        tasks.append(task)

        return tasks

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
        for wrapper in jjb_job.get('wrappers', []):
            if isinstance(wrapper, dict):
                timeout = wrapper.get('build-timeout', {})
                if isinstance(timeout, dict):
                    timeout = timeout.get('timeout')
                    if timeout:
                        timeout = timeout * 60

        with open(jobdir.playbook, 'w') as playbook:
            tasks = []
            main_block = []
            error_block = []
            tasks.append(dict(block=main_block,
                              rescue=error_block))

            task = dict(file=dict(path='/tmp/console.html', state='absent'))
            main_block.append(task)

            task = dict(zuul_console=dict(path='/tmp/console.html', port=8088))
            main_block.append(task)

            task = dict(file=dict(path=parameters['WORKSPACE'],
                                  state='directory'))
            main_block.append(task)

            # TODO: remove once zuul-worker DIB element has landed
            main_block.append(dict(shell="[ -f /usr/bin/yum ] && "
                                   "sudo /usr/bin/yum install "
                                   "libselinux-python || "
                                   "/bin/true"))

            for builder in jjb_job.get('builders', []):
                if 'shell' in builder:
                    main_block.extend(
                        self._makeBuilderTask(jobdir, builder,
                                              parameters, timeout))
            task = dict(zuul_log=dict(msg="Job complete, result: SUCCESS"))
            main_block.append(task)

            task = dict(zuul_log=dict(msg="Job complete, result: FAILURE"))
            error_block.append(task)

            play = dict(hosts='node', name='Job body',
                        tasks=tasks)
            playbook.write(yaml.dump([play], default_flow_style=False))

        with open(jobdir.post_playbook, 'w') as playbook:
            tasks = []
            for publisher in jjb_job.get('publishers', []):
                if 'scp' in publisher:
                    tasks.extend(self._makeSCPTask(jobdir, publisher,
                                                   parameters))
                if 'ftp' in publisher:
                    tasks.extend(self._makeFTPTask(jobdir, publisher,
                                                   parameters))
            play = dict(hosts='node', name='Publishers',
                        tasks=tasks)
            playbook.write(yaml.dump([play], default_flow_style=False))

        with open(jobdir.config, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % jobdir.inventory)
            config.write('host_key_checking = False\n')
            config.write('private_key_file = %s\n' % self.private_key_file)

            callback_path = zuul.ansible.plugins.callback_plugins.__file__
            callback_path = os.path.abspath(callback_path)
            callback_path = os.path.dirname(callback_path)
            config.write('callback_plugins = %s\n' % callback_path)

            library_path = zuul.ansible.library.__file__
            library_path = os.path.abspath(library_path)
            library_path = os.path.dirname(library_path)
            config.write('library = %s\n' % library_path)

        return timeout

    def runAnsiblePlaybook(self, jobdir, timeout):
        self.ansible_proc = subprocess.Popen(
            ['ansible-playbook', jobdir.playbook,
             '-e', 'timeout=%s' % timeout, '-v'],
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        (out, err) = self.ansible_proc.communicate()
        for line in out.split('\n'):
            line = line[:1024]
            self.log.debug("Ansible stdout: %s" % line)
        for line in err.split('\n'):
            line = line[:1024]
            self.log.debug("Ansible stderr: %s" % line)
        ret = self.ansible_proc.wait()
        self.ansible_proc = None
        return ret == 0

    def runAnsiblePostPlaybook(self, jobdir, success):
        proc = subprocess.Popen(
            ['ansible-playbook', jobdir.post_playbook,
             '-e', 'success=%s' % success, '-v'],
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        (out, err) = proc.communicate()
        for line in out.split('\n'):
            line = line[:1024]
            self.log.debug("Ansible post stdout: %s" % line)
        for line in err.split('\n'):
            line = line[:1024]
            self.log.debug("Ansible post stderr: %s" % line)
        return proc.wait() == 0


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

        new_component = self.parser.data[component_type].get(name)
        if new_component:
            for new_sub_component in new_component[component_list_type]:
                new_components.extend(
                    self.expandComponent(component_type,
                                         new_sub_component, component_data))
        else:
            new_components.append({name: component_data})
        return new_components

    def expandMacros(self, job):
        for component_type in ['builder', 'publisher']:
            component_list_type = component_type + 's'
            new_components = []
            for new_component in job.get(component_list_type, []):
                new_components.extend(self.expandComponent(component_type,
                                                           new_component, {}))
            job[component_list_type] = new_components
