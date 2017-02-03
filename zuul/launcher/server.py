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
import yaml

import gear

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


class JobDirPlaybook(object):
    def __init__(self, root):
        self.root = root
        self.secure = None
        self.path = None


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
        self.vars = os.path.join(self.ansible_root, 'vars.yaml')
        self.playbook_root = os.path.join(self.ansible_root, 'playbook')
        os.makedirs(self.playbook_root)
        self.playbook = JobDirPlaybook(self.playbook_root)
        self.pre_playbooks = []
        self.post_playbooks = []
        self.config = os.path.join(self.ansible_root, 'ansible.cfg')
        self.ansible_log = os.path.join(self.ansible_root, 'ansible_log.txt')

    def addPrePlaybook(self):
        count = len(self.pre_playbooks)
        root = os.path.join(self.ansible_root, 'pre_playbook_%i' % (count,))
        os.makedirs(root)
        playbook = JobDirPlaybook(root)
        self.pre_playbooks.append(playbook)
        return playbook

    def addPostPlaybook(self):
        count = len(self.post_playbooks)
        root = os.path.join(self.ansible_root, 'post_playbook_%i' % (count,))
        os.makedirs(root)
        playbook = JobDirPlaybook(root)
        self.post_playbooks.append(playbook)
        return playbook

    def cleanup(self):
        if not self.keep:
            shutil.rmtree(self.root)

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        self.cleanup()


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

        self.job_workers = {}

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
                if command != '_stop':
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
        self.job_workers[job.unique] = AnsibleJob(self, job)
        self.job_workers[job.unique].run()

    def finishJob(self, unique):
        del(self.job_workers[unique])

    def stopJob(self, job):
        try:
            args = json.loads(job.arguments)
            self.log.debug("Stop job with arguments: %s" % (args,))
            unique = args['uuid']
            job_worker = self.job_workers.get(unique)
            if not job_worker:
                self.log.debug("Unable to find worker for job %s" % (unique,))
                return
            try:
                job_worker.stop()
            except Exception:
                self.log.exception("Exception sending stop command "
                                   "to worker:")
        finally:
            job.sendWorkComplete()

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


class AnsibleJob(object):
    log = logging.getLogger("zuul.AnsibleJob")

    RESULT_NORMAL = 1
    RESULT_TIMED_OUT = 2
    RESULT_UNREACHABLE = 3
    RESULT_ABORTED = 4

    def __init__(self, launcher_server, job):
        self.launcher_server = launcher_server
        self.job = job
        self.jobdir = None
        self.proc = None
        self.proc_lock = threading.Lock()
        self.running = False
        self.aborted = False

        if self.launcher_server.config.has_option(
            'launcher', 'private_key_file'):
            self.private_key_file = self.launcher_server.config.get(
                'launcher', 'private_key_file')
        else:
            self.private_key_file = '~/.ssh/id_rsa'

    def run(self):
        self.running = True
        self.thread = threading.Thread(target=self.launch)
        self.thread.start()

    def stop(self):
        self.aborted = True
        self.abortRunningProc()
        self.thread.join()

    def launch(self):
        try:
            self.jobdir = JobDir()
            self._launch()
        except Exception:
            self.log.exception("Exception while launching job")
            self.job.sendWorkException(traceback.format_exc())
        finally:
            self.running = False
            try:
                self.jobdir.cleanup()
            except Exception:
                self.log.exception("Error cleaning up jobdir:")
            try:
                self.launcher_server.finishJob(self.job.unique)
            except Exception:
                self.log.exception("Error finalizing job thread:")

    def _launch(self):
        self.log.debug("Job %s: beginning" % (self.job.unique,))
        self.log.debug("Job %s: args: %s" % (self.job.unique,
                                             self.job.arguments,))
        self.log.debug("Job %s: job root at %s" %
                       (self.job.unique, self.jobdir.root))
        args = json.loads(self.job.arguments)
        tasks = []
        for project in args['projects']:
            self.log.debug("Job %s: updating project %s" %
                           (self.job.unique, project['name']))
            tasks.append(self.launcher_server.update(
                project['name'], project['url']))
        for task in tasks:
            task.wait()

        self.log.debug("Job %s: git updates complete" % (self.job.unique,))
        merger = self.launcher_server._getMerger(self.jobdir.git_root)
        merge_items = [i for i in args['items'] if i.get('refspec')]
        if merge_items:
            commit = merger.mergeChanges(merge_items)  # noqa
        else:
            commit = args['items'][-1]['newrev']  # noqa

        # is the playbook in a repo that we have already prepared?
        self.preparePlaybookRepos(args)

        # TODOv3: Ansible the ansible thing here.
        self.prepareAnsibleFiles(args)

        data = {
            'manager': self.launcher_server.hostname,
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

        self.job.sendWorkData(json.dumps(data))
        self.job.sendWorkStatus(0, 100)

        result = self.runPlaybooks()

        if result is None:
            self.job.sendWorkFail()
            return
        result = dict(result=result)
        self.job.sendWorkComplete(json.dumps(result))

    def runPlaybooks(self):
        result = None

        for playbook in self.jobdir.pre_playbooks:
            pre_status, pre_code = self.runAnsiblePlaybook(playbook)
            if pre_status != self.RESULT_NORMAL or pre_code != 0:
                # These should really never fail, so return None and have
                # zuul try again
                return result

        job_status, job_code = self.runAnsiblePlaybook(self.jobdir.playbook)
        if job_status == self.RESULT_TIMED_OUT:
            return 'TIMED_OUT'
        if job_status == self.RESULT_ABORTED:
            return 'ABORTED'
        if job_status != self.RESULT_NORMAL:
            # The result of the job is indeterminate.  Zuul will
            # run it again.
            return result

        success = (job_code == 0)
        if success:
            result = 'SUCCESS'
        else:
            result = 'FAILURE'

        for playbook in self.jobdir.post_playbooks:
            post_status, post_code = self.runAnsiblePlaybook(
                playbook, success)
            if post_status != self.RESULT_NORMAL or post_code != 0:
                result = 'POST_FAILURE'
        return result

    def getHostList(self, args):
        # TODOv3: the localhost addition is temporary so we have
        # something to exercise ansible.
        hosts = [('localhost', dict(ansible_connection='local'))]
        for node in args['nodes']:
            # TODOv3: the connection should almost certainly not be
            # local.
            hosts.append((node['name'], dict(ansible_connection='local')))
        return hosts

    def findPlaybook(self, path):
        for ext in ['.yaml', '.yml']:
            fn = path + ext
            if os.path.exists(fn):
                return fn
        raise Exception("Unable to find playbook %s" % path)

    def preparePlaybookRepos(self, args):
        for playbook in args['pre_playbooks']:
            jobdir_playbook = self.jobdir.addPrePlaybook()
            self.preparePlaybookRepo(jobdir_playbook, playbook, args)

        jobdir_playbook = self.jobdir.playbook
        self.preparePlaybookRepo(jobdir_playbook, args['playbook'], args)

        for playbook in args['post_playbooks']:
            jobdir_playbook = self.jobdir.addPostPlaybook()
            self.preparePlaybookRepo(jobdir_playbook, playbook, args)

    def preparePlaybookRepo(self, jobdir_playbook, playbook, args):
        # Check out the playbook repo if needed and set the path to
        # the playbook that should be run.
        jobdir_playbook.secure = playbook['secure']
        source = self.launcher_server.connections.getSource(
            playbook['connection'])
        project = source.getProject(playbook['project'])
        # TODO(jeblair): construct the url in the merger itself
        url = source.getGitUrl(project)
        if not playbook['secure']:
            # This is a project repo, so it is safe to use the already
            # checked out version (from speculative merging) of the
            # playbook
            for i in args['items']:
                if (i['connection_name'] == playbook['connection'] and
                    i['project'] == playbook['project']):
                    # We already have this repo prepared
                    path = os.path.join(self.jobdir.git_root,
                                        project.name,
                                        playbook['path'])
                    jobdir_playbook.path = self.findPlaybook(path)
                    return
        # The playbook repo is either a config repo, or it isn't in
        # the stack of changes we are testing, so check out the branch
        # tip into a dedicated space.

        merger = self.launcher_server._getMerger(jobdir_playbook.root)
        merger.checkoutBranch(project.name, url, playbook['branch'])

        path = os.path.join(jobdir_playbook.root,
                            project.name,
                            playbook['path'])
        jobdir_playbook.path = self.findPlaybook(path)

    def prepareAnsibleFiles(self, args):
        with open(self.jobdir.inventory, 'w') as inventory:
            for host_name, host_vars in self.getHostList(args):
                inventory.write(host_name)
                inventory.write(' ')
                for k, v in host_vars.items():
                    inventory.write('%s=%s' % (k, v))
                inventory.write('\n')
        with open(self.jobdir.vars, 'w') as vars_yaml:
            zuul_vars = dict(zuul=args['zuul'])
            vars_yaml.write(
                yaml.safe_dump(zuul_vars, default_flow_style=False))
        with open(self.jobdir.config, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % self.jobdir.inventory)
            config.write('local_tmp = %s/.ansible/local_tmp\n' %
                         self.jobdir.root)
            config.write('remote_tmp = %s/.ansible/remote_tmp\n' %
                         self.jobdir.root)
            config.write('private_key_file = %s\n' % self.private_key_file)
            config.write('retry_files_enabled = False\n')
            config.write('log_path = %s\n' % self.jobdir.ansible_log)
            config.write('gathering = explicit\n')
            config.write('library = %s\n'
                         % self.launcher_server.library_dir)
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
                "-o UserKnownHostsFile=%s" % self.jobdir.known_hosts
            config.write('ssh_args = %s\n' % ssh_args)

    def _ansibleTimeout(self, msg):
        self.log.warning(msg)
        self.abortRunningProc()

    def abortRunningProc(self):
        with self.proc_lock:
            if not self.proc:
                self.log.debug("Abort: no process is running")
                return
            self.log.debug("Abort: sending kill signal to job "
                           "process group")
            try:
                pgid = os.getpgid(self.proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                self.log.exception("Exception while killing "
                                   "ansible process:")

    def runAnsible(self, cmd, timeout):
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'

        with self.proc_lock:
            if self.aborted:
                return (self.RESULT_ABORTED, None)
            self.log.debug("Ansible command: %s" % (cmd,))
            self.proc = subprocess.Popen(
                cmd,
                cwd=self.jobdir.ansible_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                env=env_copy,
            )

        ret = None
        watchdog = Watchdog(timeout + ANSIBLE_WATCHDOG_GRACE,
                            self._ansibleTimeout,
                            ("Ansible timeout exceeded",))
        watchdog.start()
        try:
            for line in iter(self.proc.stdout.readline, b''):
                line = line[:1024].rstrip()
                self.log.debug("Ansible output: %s" % (line,))
            ret = self.proc.wait()
        finally:
            watchdog.stop()
        self.log.debug("Ansible exit code: %s" % (ret,))

        with self.proc_lock:
            self.proc = None

        if watchdog.timed_out:
            return (self.RESULT_TIMED_OUT, None)
        if ret == 3:
            # AnsibleHostUnreachable: We had a network issue connecting to
            # our zuul-worker.
            return (self.RESULT_UNREACHABLE, None)
        elif ret == -9:
            # Received abort request.
            return (self.RESULT_ABORTED, None)

        return (self.RESULT_NORMAL, ret)

    def runAnsiblePlaybook(self, playbook, success=None):
        env_copy = os.environ.copy()
        env_copy['LOGNAME'] = 'zuul'

        if False:  # TODOv3: self.options['verbose']:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', playbook.path]

        if success is not None:
            cmd.extend(['-e', 'success=%s' % str(bool(success))])

        cmd.extend(['-e@%s' % self.jobdir.vars, verbose])

        # TODOv3: get this from the job
        timeout = 60

        return self.runAnsible(cmd, timeout)
