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
import signal
import socket
import subprocess
import tempfile
import threading
import time
import traceback

import gear
import yaml

import zuul.merger
import zuul.ansible.library
from zuul.lib import commandsocket

ANSIBLE_WATCHDOG_GRACE = 5 * 60


class Watchdog(object):
    def __init__(self, timeout, function, args):
        self.timeout = timeout
        self.function = function
        self.args = args
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.timed_out = None

    def _run(self):
        while self._running and time.time() < self.end:
            time.sleep(10)
        if self._running:
            self.timed_out = True
            self.function(*self.args)
        self.timed_out = False

    def start(self):
        self._running = True
        self.end = time.time() + self.timeout
        self.thread.start()

    def stop(self):
        self._running = False

# TODOv3(mordred): put git repos in a hierarchy that includes source
# hostname, eg: git.openstack.org/openstack/nova.  Also, configure
# sources to have an alias, so that the review.openstack.org source
# repos end up in git.openstack.org.


class JobDir(object):
    def __init__(self, keep=False):
        self.keep = keep
        self.root = tempfile.mkdtemp()
        self.git_root = os.path.join(self.root, 'git')
        os.makedirs(self.git_root)
        self.ansible_root = os.path.join(self.root, 'ansible')
        os.makedirs(self.ansible_root)
        self.known_hosts = os.path.join(self.ansible_root, 'known_hosts')
        self.inventory = os.path.join(self.ansible_root, 'inventory')
        self.playbook = os.path.join(self.ansible_root, 'playbook')
        self.post_playbook = os.path.join(self.ansible_root, 'post_playbook')
        self.config = os.path.join(self.ansible_root, 'ansible.cfg')
        self.ansible_log = os.path.join(self.ansible_root, 'ansible_log.txt')

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if not self.keep:
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

    def __init__(self, config, connections={}, keep_jobdir=False):
        self.config = config
        self.keep_jobdir = keep_jobdir
        # TODOv3(mordred): make the launcher name more unique --
        # perhaps hostname+pid.
        self.hostname = socket.gethostname()
        self.zuul_url = config.get('merger', 'zuul_url')
        self.command_map = dict(
            stop=self.stop,
            pause=self.pause,
            unpause=self.unpause,
            graceful=self.graceful,
            verbose=self.verboseOn,
            unverbose=self.verboseOff,
        )

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
        if self.config.has_option('launcher', 'private_key_file'):
            self.private_key_file = config.get('launcher', 'private_key_file')
        else:
            self.private_key_file = '~/.ssh/id_rsa'

        self.connections = connections
        self.merger = self._getMerger(self.merge_root)
        self.update_queue = DeduplicateQueue()

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

        library_path = os.path.dirname(os.path.abspath(
            zuul.ansible.library.__file__))
        for fn in os.listdir(library_path):
            shutil.copy(os.path.join(library_path, fn), self.library_dir)

    def _getMerger(self, root):
        return zuul.merger.merger.Merger(root, self.connections,
                                         self.merge_email, self.merge_name)

    def start(self):
        self._running = True
        self._command_running = True
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

        self.log.debug("Starting command processor")
        self.command_socket.start()
        self.command_thread = threading.Thread(target=self.runCommand)
        self.command_thread.daemon = True
        self.command_thread.start()

        self.log.debug("Starting worker")
        self.update_thread = threading.Thread(target=self._updateLoop)
        self.update_thread.daemon = True
        self.update_thread.start()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("launcher:launch")
        self.worker.registerFunction("launcher:stop:%s" % self.hostname)
        self.worker.registerFunction("merger:merge")
        self.worker.registerFunction("merger:cat")

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self.worker.shutdown()
        self._command_running = False
        self.command_socket.stop()
        self.log.debug("Stopped")

    def pause(self):
        # TODOv3: implement
        pass

    def unpause(self):
        # TODOv3: implement
        pass

    def graceful(self):
        # TODOv3: implement
        pass

    def verboseOn(self):
        # TODOv3: implement
        pass

    def verboseOff(self):
        # TODOv3: implement
        pass

    def join(self):
        self.update_thread.join()
        self.thread.join()

    def runCommand(self):
        while self._command_running:
            try:
                command = self.command_socket.get()
                self.command_map[command]()
            except Exception:
                self.log.exception("Exception while processing command")

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
                        self.launchJob(job)
                    elif job.name.startswith('launcher:stop'):
                        self.log.debug("Got stop job: %s" % job.unique)
                        self.stopJob(job)
                    elif job.name == 'merger:cat':
                        self.log.debug("Got cat job: %s" % job.unique)
                        self.cat(job)
                    elif job.name == 'merger:merge':
                        self.log.debug("Got merge job: %s" % job.unique)
                        self.merge(job)
                    else:
                        self.log.error("Unable to handle job %s" % job.name)
                        job.sendWorkFail()
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(traceback.format_exc())
            except Exception:
                self.log.exception("Exception while getting job")

    def launchJob(self, job):
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
            merge_items = [i for i in args['items'] if i.get('refspec')]
            if merge_items:
                commit = merger.mergeChanges(merge_items)  # noqa
            else:
                commit = args['items'][-1]['newrev']  # noqa

            # TODOv3: Ansible the ansible thing here.
            self.prepareAnsibleFiles(jobdir, args)

            data = {
                'manager': self.hostname,
                'url': 'https://server/job/{}/0/'.format(args['job']),
                'worker_name': 'My Worker',
            }

            # TODOv3:
            # 'name': self.name,
            # 'manager': self.launch_server.hostname,
            # 'worker_name': 'My Worker',
            # 'worker_hostname': 'localhost',
            # 'worker_ips': ['127.0.0.1', '192.168.1.1'],
            # 'worker_fqdn': 'zuul.example.org',
            # 'worker_program': 'FakeBuilder',
            # 'worker_version': 'v1.1',
            # 'worker_extra': {'something': 'else'}

            job.sendWorkData(json.dumps(data))
            job.sendWorkStatus(0, 100)

            result = self.runAnsible(jobdir, job)
            if result is None:
                job.sendWorkFail()
                return
            result = dict(result=result)
            job.sendWorkComplete(json.dumps(result))

    def stopJob(self, job):
        # TODOv3: implement.
        job.sendWorkComplete()

    def getHostList(self, args):
        # TODOv3: the localhost addition is temporary so we have
        # something to exercise ansible.
        hosts = [('localhost', dict(ansible_connection='local'))]
        for node in args['nodes']:
            # TODOv3: the connection should almost certainly not be
            # local.
            hosts.append((node['name'], dict(ansible_connection='local')))
        return hosts

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
            config.write('local_tmp = %s/.ansible/local_tmp\n' % jobdir.root)
            config.write('remote_tmp = %s/.ansible/remote_tmp\n' % jobdir.root)
            config.write('private_key_file = %s\n' % self.private_key_file)
            config.write('retry_files_enabled = False\n')
            config.write('log_path = %s\n' % jobdir.ansible_log)
            config.write('gathering = explicit\n')
            config.write('library = %s\n' % self.library_dir)
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
        self.log.warning(msg)
        self.abortRunningProc(proc)

    def abortRunningProc(self, proc):
        aborted = False
        self.log.debug("Abort: sending kill signal to job "
                       "process group")
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
            aborted = True
        except Exception:
            self.log.exception("Exception while killing "
                               "ansible process:")
        return aborted

    def runAnsible(self, jobdir, job):
        # Job is included here for the benefit of the test framework.
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'

        if False:  # TODOv3: self.options['verbose']:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', jobdir.playbook, verbose]
        self.log.debug("Ansible command: %s" % (cmd,))
        # TODOv3: verbose
        proc = subprocess.Popen(
            cmd,
            cwd=jobdir.ansible_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env_copy,
        )

        ret = None
        # TODOv3: get this from the job
        timeout = 60
        watchdog = Watchdog(timeout + ANSIBLE_WATCHDOG_GRACE,
                            self._ansibleTimeout,
                            (proc,
                             "Ansible timeout exceeded"))
        watchdog.start()
        try:
            for line in iter(proc.stdout.readline, b''):
                line = line[:1024].rstrip()
                self.log.debug("Ansible output: %s" % (line,))
            ret = proc.wait()
        finally:
            watchdog.stop()
        self.log.debug("Ansible exit code: %s" % (ret,))

        if watchdog.timed_out:
            return 'TIMED_OUT'
        if ret == 3:
            # AnsibleHostUnreachable: We had a network issue connecting to
            # our zuul-worker.
            return None
        elif ret == -9:
            # Received abort request.
            return None

        if ret == 0:
            return 'SUCCESS'
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

    def merge(self, job):
        args = json.loads(job.arguments)
        ret = self.merger.mergeChanges(args['items'], args.get('files'))
        result = dict(merged=(ret is not None),
                      zuul_url=self.zuul_url)
        if args.get('files'):
            result['commit'], result['files'] = ret
        else:
            result['commit'] = ret
        job.sendWorkComplete(json.dumps(result))
