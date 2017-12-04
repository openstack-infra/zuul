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
import datetime
import json
import logging
import multiprocessing
import os
import shutil
import signal
import shlex
import socket
import subprocess
import tempfile
import threading
import time
import traceback
from zuul.lib.yamlutil import yaml
from zuul.lib.config import get_default
from zuul.lib.statsd import get_statsd

try:
    import ara.plugins.callbacks as ara_callbacks
except ImportError:
    ara_callbacks = None
import gear

import zuul.merger.merger
import zuul.ansible.logconfig
from zuul.lib import commandsocket

BUFFER_LINES_FOR_SYNTAX = 200
COMMANDS = ['stop', 'pause', 'unpause', 'graceful', 'verbose',
            'unverbose', 'keep', 'nokeep']
DEFAULT_FINGER_PORT = 79


class StopException(Exception):
    """An exception raised when an inner loop is asked to stop."""
    pass


class ExecutorError(Exception):
    """A non-transient run-time executor error

    This class represents error conditions detected by the executor
    when preparing to run a job which we know are consistently fatal.
    Zuul should not reschedule the build in these cases.
    """
    pass


class RoleNotFoundError(ExecutorError):
    pass


class DiskAccountant(object):
    ''' A single thread to periodically run du and monitor a base directory

    Whenever the accountant notices a dir over limit, it will call the
    given func with an argument of the job directory. That function
    should be used to remediate the problem, generally by killing the
    job producing the disk bloat). The function will be called every
    time the problem is noticed, so it should be handled synchronously
    to avoid stacking up calls.
    '''
    log = logging.getLogger("zuul.ExecutorDiskAccountant")

    def __init__(self, jobs_base, limit, func, cache_dir, usage_func=None):
        '''
        :param str jobs_base: absolute path name of dir to be monitored
        :param int limit: maximum number of MB allowed to be in use in any one
                          subdir
        :param callable func: Function to call with overlimit dirs
        :param str cache_dir: absolute path name of dir to be passed as the
                              first argument to du. This will ensure du does
                              not count any hardlinks to files in this
                              directory against a single job.
        :param callable usage_func: Optional function to call with usage
                                    for every dir _NOT_ over limit
        '''
        # Don't cross the streams
        if cache_dir == jobs_base:
            raise Exception("Cache dir and jobs dir cannot be the same")
        self.thread = threading.Thread(target=self._run,
                                       name='diskaccountant')
        self.thread.daemon = True
        self._running = False
        self.jobs_base = jobs_base
        self.limit = limit
        self.func = func
        self.cache_dir = cache_dir
        self.usage_func = usage_func
        self.stop_event = threading.Event()

    def _run(self):
        while self._running:
            # Walk job base
            before = time.time()
            du = subprocess.Popen(
                ['du', '-m', '--max-depth=1', self.cache_dir, self.jobs_base],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            for line in du.stdout:
                (size, dirname) = line.rstrip().split()
                dirname = dirname.decode('utf8')
                if dirname == self.jobs_base or dirname == self.cache_dir:
                    continue
                if os.path.dirname(dirname) == self.cache_dir:
                    continue
                size = int(size)
                if size > self.limit:
                    self.log.info(
                        "{job} is using {size}MB (limit={limit})"
                        .format(size=size, job=dirname, limit=self.limit))
                    self.func(dirname)
                elif self.usage_func:
                    self.log.debug(
                        "{job} is using {size}MB (limit={limit})"
                        .format(size=size, job=dirname, limit=self.limit))
                    self.usage_func(dirname, size)
            du.wait()
            after = time.time()
            # Sleep half as long as that took, or 1s, whichever is longer
            delay_time = max((after - before) / 2, 1.0)
            self.stop_event.wait(delay_time)

    def start(self):
        self._running = True
        self.thread.start()

    def stop(self):
        self._running = False
        self.stop_event.set()
        # We join here to avoid whitelisting the thread -- if it takes more
        # than 5s to stop in tests, there's a problem.
        self.thread.join(timeout=5)


class Watchdog(object):
    def __init__(self, timeout, function, args):
        self.timeout = timeout
        self.function = function
        self.args = args
        self.thread = threading.Thread(target=self._run,
                                       name='watchdog')
        self.thread.daemon = True
        self.timed_out = None

    def _run(self):
        while self._running and time.time() < self.end:
            time.sleep(10)
        if self._running:
            self.timed_out = True
            self.function(*self.args)
        else:
            # Only set timed_out to false if we aren't _running
            # anymore. This means that we stopped running not because
            # of a timeout but because normal execution ended.
            self.timed_out = False

    def start(self):
        self._running = True
        self.end = time.time() + self.timeout
        self.thread.start()

    def stop(self):
        self._running = False


class SshAgent(object):
    log = logging.getLogger("zuul.ExecutorServer")

    def __init__(self):
        self.env = {}
        self.ssh_agent = None

    def start(self):
        if self.ssh_agent:
            return
        with open('/dev/null', 'r+') as devnull:
            ssh_agent = subprocess.Popen(['ssh-agent'], close_fds=True,
                                         stdout=subprocess.PIPE,
                                         stderr=devnull,
                                         stdin=devnull)
        (output, _) = ssh_agent.communicate()
        output = output.decode('utf8')
        for line in output.split("\n"):
            if '=' in line:
                line = line.split(";", 1)[0]
                (key, value) = line.split('=')
                self.env[key] = value
        self.log.info('Started SSH Agent, {}'.format(self.env))

    def stop(self):
        if 'SSH_AGENT_PID' in self.env:
            try:
                os.kill(int(self.env['SSH_AGENT_PID']), signal.SIGTERM)
            except OSError:
                self.log.exception(
                    'Problem sending SIGTERM to agent {}'.format(self.env))
            self.log.debug('Sent SIGTERM to SSH Agent, {}'.format(self.env))
            self.env = {}

    def add(self, key_path):
        env = os.environ.copy()
        env.update(self.env)
        key_path = os.path.expanduser(key_path)
        self.log.debug('Adding SSH Key {}'.format(key_path))
        try:
            subprocess.check_output(['ssh-add', key_path], env=env,
                                    stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            self.log.exception('ssh-add failed. stdout: %s, stderr: %s',
                               e.output, e.stderr)
            raise
        self.log.info('Added SSH Key {}'.format(key_path))

    def remove(self, key_path):
        env = os.environ.copy()
        env.update(self.env)
        key_path = os.path.expanduser(key_path)
        self.log.debug('Removing SSH Key {}'.format(key_path))
        subprocess.check_output(['ssh-add', '-d', key_path], env=env,
                                stderr=subprocess.PIPE)
        self.log.info('Removed SSH Key {}'.format(key_path))

    def list(self):
        if 'SSH_AUTH_SOCK' not in self.env:
            return None
        env = os.environ.copy()
        env.update(self.env)
        result = []
        for line in subprocess.Popen(['ssh-add', '-L'], env=env,
                                     stdout=subprocess.PIPE).stdout:
            line = line.decode('utf8')
            if line.strip() == 'The agent has no identities.':
                break
            result.append(line.strip())
        return result


class JobDirPlaybook(object):
    def __init__(self, root):
        self.root = root
        self.trusted = None
        self.branch = None
        self.canonical_name_and_path = None
        self.path = None
        self.roles = []
        self.roles_path = []
        self.ansible_config = os.path.join(self.root, 'ansible.cfg')
        self.project_link = os.path.join(self.root, 'project')
        self.secrets_root = os.path.join(self.root, 'secrets')
        os.makedirs(self.secrets_root)
        self.secrets = os.path.join(self.secrets_root, 'secrets.yaml')
        self.secrets_content = None

    def addRole(self):
        count = len(self.roles)
        root = os.path.join(self.root, 'role_%i' % (count,))
        os.makedirs(root)
        self.roles.append(root)
        return root


class JobDir(object):
    def __init__(self, root, keep, build_uuid):
        '''
        :param str root: Root directory for the individual job directories.
            Can be None to use the default system temp root directory.
        :param bool keep: If True, do not delete the job directory.
        :param str build_uuid: The unique build UUID. If supplied, this will
            be used as the temp job directory name. Using this will help the
            log streaming daemon find job logs.
        '''
        # root
        #   ansible (mounted in bwrap read-only)
        #     logging.json
        #     inventory.yaml
        #   .ansible (mounted in bwrap read-write)
        #     fact-cache/localhost
        #     cp
        #   playbook_0 (mounted in bwrap for each playbook read-only)
        #     secrets.yaml
        #     project -> ../trusted/project_0/...
        #     role_0 -> ../trusted/project_0/...
        #   trusted (mounted in bwrap read-only)
        #     project_0
        #       <git.example.com>
        #         <project>
        #   work (mounted in bwrap read-write)
        #     .ssh
        #       known_hosts
        #     src
        #       <git.example.com>
        #         <project>
        #     logs
        #       job-output.txt
        #     results.json
        self.keep = keep
        if root:
            tmpdir = root
        else:
            tmpdir = tempfile.gettempdir()
        self.root = os.path.join(tmpdir, build_uuid)
        os.mkdir(self.root, 0o700)
        self.work_root = os.path.join(self.root, 'work')
        os.makedirs(self.work_root)
        self.src_root = os.path.join(self.work_root, 'src')
        os.makedirs(self.src_root)
        self.log_root = os.path.join(self.work_root, 'logs')
        os.makedirs(self.log_root)
        self.ansible_root = os.path.join(self.root, 'ansible')
        os.makedirs(self.ansible_root)
        self.trusted_root = os.path.join(self.root, 'trusted')
        os.makedirs(self.trusted_root)
        ssh_dir = os.path.join(self.work_root, '.ssh')
        os.mkdir(ssh_dir, 0o700)
        # Create ansible cache directory
        self.ansible_cache_root = os.path.join(self.root, '.ansible')
        self.fact_cache = os.path.join(self.ansible_cache_root, 'fact-cache')
        os.makedirs(self.fact_cache)
        self.control_path = os.path.join(self.ansible_cache_root, 'cp')
        os.makedirs(self.control_path)
        localhost_facts = os.path.join(self.fact_cache, 'localhost')
        # NOTE(pabelanger): We do not want to leak zuul-executor facts to other
        # playbooks now that smart fact gathering is enabled by default.  We
        # can have ansible skip populating the cache with information by the
        # doing the following.
        with open(localhost_facts, 'w') as f:
            f.write('{"module_setup": true}')

        self.result_data_file = os.path.join(self.work_root, 'results.json')
        with open(self.result_data_file, 'w'):
            pass
        self.known_hosts = os.path.join(ssh_dir, 'known_hosts')
        self.inventory = os.path.join(self.ansible_root, 'inventory.yaml')
        self.logging_json = os.path.join(self.ansible_root, 'logging.json')
        self.playbooks = []  # The list of candidate playbooks
        self.playbook = None  # A pointer to the candidate we have chosen
        self.pre_playbooks = []
        self.post_playbooks = []
        self.job_output_file = os.path.join(self.log_root, 'job-output.txt')
        # We need to create the job-output.txt upfront in order to close the
        # gap between url reporting and ansible creating the file. Otherwise
        # there is a period of time where the user can click on the live log
        # link on the status page but the log streaming fails because the file
        # is not there yet.
        with open(self.job_output_file, 'w') as job_output:
            job_output.write("{now} | Job console starting...\n".format(
                now=datetime.datetime.now()
            ))
        self.trusted_projects = []
        self.trusted_project_index = {}

        # Create a JobDirPlaybook for the Ansible setup run.  This
        # doesn't use an actual playbook, but it lets us use the same
        # methods to write an ansible.cfg as the rest of the Ansible
        # runs.
        setup_root = os.path.join(self.ansible_root, 'setup_playbook')
        os.makedirs(setup_root)
        self.setup_playbook = JobDirPlaybook(setup_root)
        self.setup_playbook.trusted = True

    def addTrustedProject(self, canonical_name, branch):
        # Trusted projects are placed in their own directories so that
        # we can support using different branches of the same project
        # in different playbooks.
        count = len(self.trusted_projects)
        root = os.path.join(self.trusted_root, 'project_%i' % (count,))
        os.makedirs(root)
        self.trusted_projects.append(root)
        self.trusted_project_index[(canonical_name, branch)] = root
        return root

    def getTrustedProject(self, canonical_name, branch):
        return self.trusted_project_index.get((canonical_name, branch))

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

    def addPlaybook(self):
        count = len(self.playbooks)
        root = os.path.join(self.ansible_root, 'playbook_%i' % (count,))
        os.makedirs(root)
        playbook = JobDirPlaybook(root)
        self.playbooks.append(playbook)
        return playbook

    def cleanup(self):
        if not self.keep:
            shutil.rmtree(self.root)

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        self.cleanup()


class UpdateTask(object):
    def __init__(self, connection_name, project_name):
        self.connection_name = connection_name
        self.project_name = project_name
        self.event = threading.Event()

    def __eq__(self, other):
        if (other and other.connection_name == self.connection_name and
            other.project_name == self.project_name):
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


def _copy_ansible_files(python_module, target_dir):
        library_path = os.path.dirname(os.path.abspath(python_module.__file__))
        for fn in os.listdir(library_path):
            if fn == "__pycache__":
                continue
            full_path = os.path.join(library_path, fn)
            if os.path.isdir(full_path):
                shutil.copytree(full_path, os.path.join(target_dir, fn))
            else:
                shutil.copy(os.path.join(library_path, fn), target_dir)


def make_inventory_dict(nodes, groups, all_vars):

    hosts = {}
    for node in nodes:
        hosts[node['name']] = node['host_vars']

    inventory = {
        'all': {
            'hosts': hosts,
            'vars': all_vars,
        }
    }

    for group in groups:
        group_hosts = {}
        for node_name in group['nodes']:
            # children is a dict with None as values because we don't have
            # and per-group variables. If we did, None would be a dict
            # with the per-group variables
            group_hosts[node_name] = None
        inventory[group['name']] = {'hosts': group_hosts}

    return inventory


class AnsibleJobLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        msg, kwargs = super(AnsibleJobLogAdapter, self).process(msg, kwargs)
        msg = '[build: %s] %s' % (kwargs['extra']['job'], msg)
        return msg, kwargs


class AnsibleJob(object):
    RESULT_NORMAL = 1
    RESULT_TIMED_OUT = 2
    RESULT_UNREACHABLE = 3
    RESULT_ABORTED = 4
    RESULT_DISK_FULL = 5

    RESULT_MAP = {
        RESULT_NORMAL: 'RESULT_NORMAL',
        RESULT_TIMED_OUT: 'RESULT_TIMED_OUT',
        RESULT_UNREACHABLE: 'RESULT_UNREACHABLE',
        RESULT_ABORTED: 'RESULT_ABORTED',
        RESULT_DISK_FULL: 'RESULT_DISK_FULL',
    }

    def __init__(self, executor_server, job):
        logger = logging.getLogger("zuul.AnsibleJob")
        self.log = AnsibleJobLogAdapter(logger, {'job': job.unique})
        self.executor_server = executor_server
        self.job = job
        self.jobdir = None
        self.proc = None
        self.proc_lock = threading.Lock()
        self.running = False
        self.aborted = False
        self.aborted_reason = None
        self.thread = None
        self.private_key_file = get_default(self.executor_server.config,
                                            'executor', 'private_key_file',
                                            '~/.ssh/id_rsa')
        self.ssh_agent = SshAgent()

        self.executor_variables_file = None

        if self.executor_server.config.has_option('executor', 'variables'):
            self.executor_variables_file = self.executor_server.config.get(
                'executor', 'variables')

    def run(self):
        self.running = True
        self.thread = threading.Thread(target=self.execute,
                                       name='build-%s' % self.job.unique)
        self.thread.start()

    def stop(self, reason=None):
        self.aborted = True
        self.aborted_reason = reason
        self.abortRunningProc()

    def wait(self):
        if self.thread:
            self.thread.join()

    def execute(self):
        try:
            self.ssh_agent.start()
            self.ssh_agent.add(self.private_key_file)
            self.jobdir = JobDir(self.executor_server.jobdir_root,
                                 self.executor_server.keep_jobdir,
                                 str(self.job.unique))
            self._execute()
        except ExecutorError as e:
            result_data = json.dumps(dict(result='ERROR',
                                          error_detail=e.args[0]))
            self.log.debug("Sending result: %s" % (result_data,))
            self.job.sendWorkComplete(result_data)
        except Exception:
            self.log.exception("Exception while executing job")
            self.job.sendWorkException(traceback.format_exc())
        finally:
            self.running = False
            if self.jobdir:
                try:
                    self.jobdir.cleanup()
                except Exception:
                    self.log.exception("Error cleaning up jobdir:")
            if self.ssh_agent:
                try:
                    self.ssh_agent.stop()
                except Exception:
                    self.log.exception("Error stopping SSH agent:")
            try:
                self.executor_server.finishJob(self.job.unique)
            except Exception:
                self.log.exception("Error finalizing job thread:")

    def _execute(self):
        args = json.loads(self.job.arguments)
        self.log.debug("Beginning job %s for ref %s" %
                       (self.job.name, args['zuul']['ref']))
        self.log.debug("Job root: %s" % (self.jobdir.root,))
        tasks = []
        projects = set()

        # Make sure all projects used by the job are updated...
        for project in args['projects']:
            self.log.debug("Updating project %s" % (project,))
            tasks.append(self.executor_server.update(
                project['connection'], project['name']))
            projects.add((project['connection'], project['name']))

        # ...as well as all playbook and role projects.
        repos = []
        playbooks = (args['pre_playbooks'] + args['playbooks'] +
                     args['post_playbooks'])
        for playbook in playbooks:
            repos.append(playbook)
            repos += playbook['roles']

        for repo in repos:
            self.log.debug("Updating playbook or role %s" % (repo['project'],))
            key = (repo['connection'], repo['project'])
            if key not in projects:
                tasks.append(self.executor_server.update(*key))
                projects.add(key)

        for task in tasks:
            task.wait()

        self.log.debug("Git updates complete")
        merger = self.executor_server._getMerger(self.jobdir.src_root,
                                                 self.log)
        repos = {}
        for project in args['projects']:
            self.log.debug("Cloning %s/%s" % (project['connection'],
                                              project['name'],))
            repo = merger.getRepo(project['connection'],
                                  project['name'])
            repos[project['canonical_name']] = repo

        merge_items = [i for i in args['items'] if i.get('number')]
        if merge_items:
            if not self.doMergeChanges(merger, merge_items,
                                       args['repo_state']):
                # There was a merge conflict and we have already sent
                # a work complete result, don't run any jobs
                return

        state_items = [i for i in args['items'] if not i.get('number')]
        if state_items:
            merger.setRepoState(state_items, args['repo_state'])

        for project in args['projects']:
            repo = repos[project['canonical_name']]
            # If this project is the Zuul project and this is a ref
            # rather than a change, checkout the ref.
            if (project['canonical_name'] ==
                args['zuul']['project']['canonical_name'] and
                (not args['zuul'].get('branch')) and
                args['zuul'].get('ref')):
                ref = args['zuul']['ref']
            else:
                ref = None
            selected = self.checkoutBranch(repo,
                                           project['name'],
                                           ref,
                                           args['branch'],
                                           args['override_branch'],
                                           args['override_checkout'],
                                           project['override_branch'],
                                           project['override_checkout'],
                                           project['default_branch'])
            # Update the inventory variables to indicate the ref we
            # checked out
            p = args['zuul']['_projects'][project['canonical_name']]
            p['checkout'] = selected
        # Delete the origin remote from each repo we set up since
        # it will not be valid within the jobs.
        for repo in repos.values():
            repo.deleteRemote('origin')

        # This prepares each playbook and the roles needed for each.
        self.preparePlaybooks(args)

        self.prepareAnsibleFiles(args)
        self.writeLoggingConfig()

        data = {
            # TODO(mordred) worker_name is needed as a unique name for the
            # client to use for cancelling jobs on an executor. It's defaulting
            # to the hostname for now, but in the future we should allow
            # setting a per-executor override so that one can run more than
            # one executor on a host.
            'worker_name': self.executor_server.hostname,
            'worker_hostname': self.executor_server.hostname,
            'worker_log_port': self.executor_server.log_streaming_port
        }
        if self.executor_server.log_streaming_port != DEFAULT_FINGER_PORT:
            data['url'] = "finger://{hostname}:{port}/{uuid}".format(
                hostname=data['worker_hostname'],
                port=data['worker_log_port'],
                uuid=self.job.unique)
        else:
            data['url'] = 'finger://{hostname}/{uuid}'.format(
                hostname=data['worker_hostname'],
                uuid=self.job.unique)

        self.job.sendWorkData(json.dumps(data))
        self.job.sendWorkStatus(0, 100)

        result = self.runPlaybooks(args)

        # Stop the persistent SSH connections.
        setup_status, setup_code = self.runAnsibleCleanup(
            self.jobdir.setup_playbook)

        if self.aborted_reason == self.RESULT_DISK_FULL:
            result = 'DISK_FULL'
        data = self.getResultData()
        result_data = json.dumps(dict(result=result,
                                      data=data))
        self.log.debug("Sending result: %s" % (result_data,))
        self.job.sendWorkComplete(result_data)

    def getResultData(self):
        data = {}
        try:
            with open(self.jobdir.result_data_file) as f:
                file_data = f.read()
                if file_data:
                    data = json.loads(file_data)
        except Exception:
            self.log.exception("Unable to load result data:")
        return data

    def doMergeChanges(self, merger, items, repo_state):
        ret = merger.mergeChanges(items, repo_state=repo_state)
        if not ret:  # merge conflict
            result = dict(result='MERGER_FAILURE')
            self.job.sendWorkComplete(json.dumps(result))
            return False
        recent = ret[3]
        for key, commit in recent.items():
            (connection, project, branch) = key
            repo = merger.getRepo(connection, project)
            repo.setRef('refs/heads/' + branch, commit)
        return True

    def checkoutBranch(self, repo, project_name, ref, zuul_branch,
                       job_override_branch, job_override_checkout,
                       project_override_branch, project_override_checkout,
                       project_default_branch):
        branches = repo.getBranches()
        refs = [r.name for r in repo.getRefs()]
        selected_ref = None
        if project_override_checkout in refs:
            selected_ref = project_override_checkout
            self.log.info("Checking out %s project override ref %s",
                          project_name, selected_ref)
        elif project_override_branch in branches:
            selected_ref = project_override_branch
            self.log.info("Checking out %s project override branch %s",
                          project_name, selected_ref)
        elif job_override_checkout in refs:
            selected_ref = job_override_checkout
            self.log.info("Checking out %s job override ref %s",
                          project_name, selected_ref)
        elif job_override_branch in branches:
            selected_ref = job_override_branch
            self.log.info("Checking out %s job override branch %s",
                          project_name, selected_ref)
        elif ref and ref.startswith('refs/heads/'):
            selected_ref = ref[len('refs/heads/'):]
            self.log.info("Checking out %s branch ref %s",
                          project_name, selected_ref)
        elif ref and ref.startswith('refs/tags/'):
            selected_ref = ref[len('refs/tags/'):]
            self.log.info("Checking out %s tag ref %s",
                          project_name, selected_ref)
        elif zuul_branch and zuul_branch in branches:
            selected_ref = zuul_branch
            self.log.info("Checking out %s zuul branch %s",
                          project_name, selected_ref)
        elif project_default_branch in branches:
            selected_ref = project_default_branch
            self.log.info("Checking out %s project default branch %s",
                          project_name, selected_ref)
        else:
            raise ExecutorError("Project %s does not have the "
                                "default branch %s" %
                                (project_name, project_default_branch))
        repo.checkout(selected_ref)
        return selected_ref

    def runPlaybooks(self, args):
        result = None

        # Run the Ansible 'setup' module on all hosts in the inventory
        # at the start of the job with a 60 second timeout.  If we
        # aren't able to connect to all the hosts and gather facts
        # within that timeout, there is likely a network problem
        # between here and the hosts in the inventory; return them and
        # reschedule the job.
        setup_status, setup_code = self.runAnsibleSetup(
            self.jobdir.setup_playbook)
        if setup_status != self.RESULT_NORMAL or setup_code != 0:
            return result

        pre_failed = False
        success = False
        for index, playbook in enumerate(self.jobdir.pre_playbooks):
            # TODOv3(pabelanger): Implement pre-run timeout setting.
            pre_status, pre_code = self.runAnsiblePlaybook(
                playbook, args['timeout'], phase='pre', index=index)
            if pre_status != self.RESULT_NORMAL or pre_code != 0:
                # These should really never fail, so return None and have
                # zuul try again
                pre_failed = True
                break

        if not pre_failed:
            job_status, job_code = self.runAnsiblePlaybook(
                self.jobdir.playbook, args['timeout'], phase='run')
            if job_status == self.RESULT_ABORTED:
                return 'ABORTED'
            elif job_status == self.RESULT_TIMED_OUT:
                # Set the pre-failure flag so this doesn't get
                # overridden by a post-failure.
                pre_failed = True
                result = 'TIMED_OUT'
            elif job_status == self.RESULT_NORMAL:
                success = (job_code == 0)
                if success:
                    result = 'SUCCESS'
                else:
                    result = 'FAILURE'
            else:
                # The result of the job is indeterminate.  Zuul will
                # run it again.
                return None

        for index, playbook in enumerate(self.jobdir.post_playbooks):
            # TODOv3(pabelanger): Implement post-run timeout setting.
            post_status, post_code = self.runAnsiblePlaybook(
                playbook, args['timeout'], success, phase='post', index=index)
            if post_status == self.RESULT_ABORTED:
                return 'ABORTED'
            if post_status != self.RESULT_NORMAL or post_code != 0:
                success = False
                # If we encountered a pre-failure, that takes
                # precedence over the post result.
                if not pre_failed:
                    result = 'POST_FAILURE'
                if (index + 1) == len(self.jobdir.post_playbooks):
                    self._logFinalPlaybookError()

        return result

    def _logFinalPlaybookError(self):
        # Failures in the final post playbook can include failures
        # uploading logs, which makes diagnosing issues difficult.
        # Grab the output from the last playbook from the json
        # file and log it.
        json_output = self.jobdir.job_output_file.replace('txt', 'json')
        self.log.debug("Final playbook failed")
        if not os.path.exists(json_output):
            self.log.debug("JSON logfile {logfile} is missing".format(
                logfile=json_output))
            return
        try:
            output = json.load(open(json_output, 'r'))
            last_playbook = output[-1]
            # Transform json to yaml - because it's easier to read and given
            # the size of the data it'll be extra-hard to read this as an
            # all on one line stringified nested dict.
            yaml_out = yaml.safe_dump(last_playbook, default_flow_style=False)
            for line in yaml_out.split('\n'):
                self.log.debug(line)
        except Exception:
            self.log.exception(
                "Could not decode json from {logfile}".format(
                    logfile=json_output))

    def getHostList(self, args):
        hosts = []
        for node in args['nodes']:
            # NOTE(mordred): This assumes that the nodepool launcher
            # and the zuul executor both have similar network
            # characteristics, as the launcher will do a test for ipv6
            # viability and if so, and if the node has an ipv6
            # address, it will be the interface_ip.  force-ipv4 can be
            # set to True in the clouds.yaml for a cloud if this
            # results in the wrong thing being in interface_ip
            # TODO(jeblair): Move this notice to the docs.
            ip = node.get('interface_ip')
            port = node.get('ssh_port', 22)
            host_vars = dict(
                ansible_host=ip,
                ansible_user=self.executor_server.default_username,
                ansible_port=port,
                nodepool=dict(
                    label=node.get('label'),
                    az=node.get('az'),
                    cloud=node.get('cloud'),
                    provider=node.get('provider'),
                    region=node.get('region'),
                    interface_ip=node.get('interface_ip'),
                    public_ipv4=node.get('public_ipv4'),
                    private_ipv4=node.get('private_ipv4'),
                    public_ipv6=node.get('public_ipv6')))

            username = node.get('username')
            if username:
                host_vars['ansible_user'] = username

            host_keys = []
            for key in node.get('host_keys'):
                if port != 22:
                    host_keys.append("[%s]:%s %s" % (ip, port, key))
                else:
                    host_keys.append("%s %s" % (ip, key))

            hosts.append(dict(
                name=node['name'],
                host_vars=host_vars,
                host_keys=host_keys))
        return hosts

    def _blockPluginDirs(self, path):
        '''Prevent execution of playbooks or roles with plugins

        Plugins are loaded from roles and also if there is a plugin
        dir adjacent to the playbook.  Throw an error if the path
        contains a location that would cause a plugin to get loaded.

        '''
        for entry in os.listdir(path):
            if os.path.isdir(entry) and entry.endswith('_plugins'):
                raise ExecutorError(
                    "Ansible plugin dir %s found adjacent to playbook %s in "
                    "non-trusted repo." % (entry, path))

    def findPlaybook(self, path, trusted=False):
        if os.path.exists(path):
            if not trusted:
                playbook_dir = os.path.dirname(os.path.abspath(path))
                self._blockPluginDirs(playbook_dir)
            return path
        raise ExecutorError("Unable to find playbook %s" % path)

    def preparePlaybooks(self, args):
        self.writeAnsibleConfig(self.jobdir.setup_playbook)

        for playbook in args['pre_playbooks']:
            jobdir_playbook = self.jobdir.addPrePlaybook()
            self.preparePlaybook(jobdir_playbook, playbook, args)

        for playbook in args['playbooks']:
            jobdir_playbook = self.jobdir.addPlaybook()
            self.preparePlaybook(jobdir_playbook, playbook, args)
            if jobdir_playbook.path is not None:
                self.jobdir.playbook = jobdir_playbook
                break

        if self.jobdir.playbook is None:
            raise ExecutorError("No playbook specified")

        for playbook in args['post_playbooks']:
            jobdir_playbook = self.jobdir.addPostPlaybook()
            self.preparePlaybook(jobdir_playbook, playbook, args)

    def preparePlaybook(self, jobdir_playbook, playbook, args):
        self.log.debug("Prepare playbook repo for %s" %
                       (playbook['project'],))
        # Check out the playbook repo if needed and set the path to
        # the playbook that should be run.
        source = self.executor_server.connections.getSource(
            playbook['connection'])
        project = source.getProject(playbook['project'])
        jobdir_playbook.trusted = playbook['trusted']
        jobdir_playbook.branch = playbook['branch']
        jobdir_playbook.canonical_name_and_path = os.path.join(
            project.canonical_name, playbook['path'])
        path = None
        if not playbook['trusted']:
            # This is a project repo, so it is safe to use the already
            # checked out version (from speculative merging) of the
            # playbook
            for i in args['items']:
                if (i['connection'] == playbook['connection'] and
                    i['project'] == playbook['project']):
                    # We already have this repo prepared
                    path = os.path.join(self.jobdir.src_root,
                                        project.canonical_hostname,
                                        project.name,
                                        playbook['path'])
                    break
        if not path:
            # The playbook repo is either a config repo, or it isn't in
            # the stack of changes we are testing, so check out the branch
            # tip into a dedicated space.
            path = self.checkoutTrustedProject(project, playbook['branch'])
            path = os.path.join(path, playbook['path'])

        jobdir_playbook.path = self.findPlaybook(
            path,
            trusted=playbook['trusted'])

        # If this playbook doesn't exist, don't bother preparing
        # roles.
        if not jobdir_playbook.path:
            return

        for role in playbook['roles']:
            self.prepareRole(jobdir_playbook, role, args)

        secrets = playbook['secrets']
        if secrets:
            if 'zuul' in secrets:
                # We block this in configloader, but block it here too to make
                # sure that a job doesn't pass secrets named zuul.
                raise Exception("Defining secrets named 'zuul' is not allowed")
            jobdir_playbook.secrets_content = yaml.safe_dump(
                secrets, default_flow_style=False)

        self.writeAnsibleConfig(jobdir_playbook)

    def checkoutTrustedProject(self, project, branch):
        root = self.jobdir.getTrustedProject(project.canonical_name,
                                             branch)
        if not root:
            root = self.jobdir.addTrustedProject(project.canonical_name,
                                                 branch)
            merger = self.executor_server._getMerger(root, self.log)
            merger.checkoutBranch(project.connection_name, project.name,
                                  branch)

        path = os.path.join(root,
                            project.canonical_hostname,
                            project.name)
        return path

    def prepareRole(self, jobdir_playbook, role, args):
        if role['type'] == 'zuul':
            root = jobdir_playbook.addRole()
            self.prepareZuulRole(jobdir_playbook, role, args, root)

    def findRole(self, path, trusted=False):
        d = os.path.join(path, 'tasks')
        if os.path.isdir(d):
            # This is a bare role
            if not trusted:
                self._blockPluginDirs(path)
            # None signifies that the repo is a bare role
            return None
        d = os.path.join(path, 'roles')
        if os.path.isdir(d):
            # This repo has a collection of roles
            if not trusted:
                self._blockPluginDirs(d)
                for entry in os.listdir(d):
                    entry_path = os.path.join(d, entry)
                    if os.path.isdir(entry_path):
                        self._blockPluginDirs(entry_path)
            return d
        # It is neither a bare role, nor a collection of roles
        raise RoleNotFoundError("Unable to find role in %s" % (path,))

    def prepareZuulRole(self, jobdir_playbook, role, args, root):
        self.log.debug("Prepare zuul role for %s" % (role,))
        # Check out the role repo if needed
        source = self.executor_server.connections.getSource(
            role['connection'])
        project = source.getProject(role['project'])
        name = role['target_name']
        path = None

        if not jobdir_playbook.trusted:
            # This playbook is untrested.  Use the already checked out
            # version (from speculative merging) of the role if it
            # exists.

            for i in args['items']:
                if (i['connection'] == role['connection'] and
                    i['project'] == role['project']):
                    # We already have this repo prepared; use it.
                    path = os.path.join(self.jobdir.src_root,
                                        project.canonical_hostname,
                                        project.name)
                    break

        if not path:
            # This is a trusted playbook or the role did not appear
            # in the dependency chain for the change (in which case,
            # there is no existing untrusted checkout of it).  Check
            # out the branch tip into a dedicated space.
            path = self.checkoutTrustedProject(project, 'master')

        # The name of the symlink is the requested name of the role
        # (which may be the repo name or may be something else; this
        # can come into play if this is a bare role).
        link = os.path.join(root, name)
        link = os.path.realpath(link)
        if not link.startswith(os.path.realpath(root)):
            raise ExecutorError("Invalid role name %s", name)
        os.symlink(path, link)

        try:
            role_path = self.findRole(link, trusted=jobdir_playbook.trusted)
        except RoleNotFoundError:
            if role['implicit']:
                self.log.info("Implicit role not found in %s", link)
                return
            raise
        if role_path is None:
            # In the case of a bare role, add the containing directory
            role_path = root
        self.log.debug("Adding role path %s", role_path)
        jobdir_playbook.roles_path.append(role_path)

    def prepareAnsibleFiles(self, args):
        all_vars = args['vars'].copy()
        # TODO(mordred) Hack to work around running things with python3
        all_vars['ansible_python_interpreter'] = '/usr/bin/python2'
        if 'zuul' in all_vars:
            # We block this in configloader, but block it here too to make
            # sure that a job doesn't pass variables named zuul.
            raise Exception("Defining vars named 'zuul' is not allowed")
        all_vars['zuul'] = args['zuul'].copy()
        all_vars['zuul']['executor'] = dict(
            hostname=self.executor_server.hostname,
            src_root=self.jobdir.src_root,
            log_root=self.jobdir.log_root,
            work_root=self.jobdir.work_root,
            result_data_file=self.jobdir.result_data_file)

        nodes = self.getHostList(args)
        inventory = make_inventory_dict(nodes, args['groups'], all_vars)

        with open(self.jobdir.inventory, 'w') as inventory_yaml:
            inventory_yaml.write(
                yaml.safe_dump(inventory, default_flow_style=False))

        with open(self.jobdir.known_hosts, 'w') as known_hosts:
            for node in nodes:
                for key in node['host_keys']:
                    known_hosts.write('%s\n' % key)

    def writeLoggingConfig(self):
        self.log.debug("Writing logging config for job %s %s",
                       self.jobdir.job_output_file,
                       self.jobdir.logging_json)
        logging_config = zuul.ansible.logconfig.JobLoggingConfig(
            job_output_file=self.jobdir.job_output_file)
        logging_config.writeJson(self.jobdir.logging_json)

    def writeAnsibleConfig(self, jobdir_playbook):
        trusted = jobdir_playbook.trusted

        # TODO(mordred) This should likely be extracted into a more generalized
        #               mechanism for deployers being able to add callback
        #               plugins.
        if ara_callbacks:
            callback_path = '%s:%s' % (
                self.executor_server.callback_dir,
                os.path.dirname(ara_callbacks.__file__))
        else:
            callback_path = self.executor_server.callback_dir
        with open(jobdir_playbook.ansible_config, 'w') as config:
            config.write('[defaults]\n')
            config.write('hostfile = %s\n' % self.jobdir.inventory)
            config.write('local_tmp = %s/local_tmp\n' %
                         self.jobdir.ansible_cache_root)
            config.write('retry_files_enabled = False\n')
            config.write('gathering = smart\n')
            config.write('fact_caching = jsonfile\n')
            config.write('fact_caching_connection = %s\n' %
                         self.jobdir.fact_cache)
            config.write('library = %s\n'
                         % self.executor_server.library_dir)
            config.write('command_warnings = False\n')
            config.write('callback_plugins = %s\n' % callback_path)
            config.write('stdout_callback = zuul_stream\n')
            config.write('filter_plugins = %s\n'
                         % self.executor_server.filter_dir)
            # bump the timeout because busy nodes may take more than
            # 10s to respond
            config.write('timeout = 30\n')
            if not trusted:
                config.write('action_plugins = %s\n'
                             % self.executor_server.action_dir)
                config.write('lookup_plugins = %s\n'
                             % self.executor_server.lookup_dir)

            if jobdir_playbook.roles_path:
                config.write('roles_path = %s\n' % ':'.join(
                    jobdir_playbook.roles_path))

            # On playbooks with secrets we want to prevent the
            # printing of args since they may be passed to a task or a
            # role. Otherwise, printing the args could be useful for
            # debugging.
            config.write('display_args_to_stdout = %s\n' %
                         str(not jobdir_playbook.secrets_content))

            # Increase the internal poll interval of ansible.
            # The default interval of 0.001s is optimized for interactive
            # ui at the expense of CPU load. As we have a non-interactive
            # automation use case a longer poll interval is more suitable
            # and reduces CPU load of the ansible process.
            config.write('internal_poll_interval = 0.01\n')

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
            config.write('control_path_dir = %s\n' % self.jobdir.control_path)
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
                self.log.exception("Exception while killing ansible process:")

    def runAnsible(self, cmd, timeout, playbook, wrapped=True):
        config_file = playbook.ansible_config
        env_copy = os.environ.copy()
        env_copy.update(self.ssh_agent.env)
        if ara_callbacks:
            env_copy['ARA_LOG_CONFIG'] = self.jobdir.logging_json
        env_copy['ZUUL_JOB_LOG_CONFIG'] = self.jobdir.logging_json
        env_copy['ZUUL_JOBDIR'] = self.jobdir.root
        pythonpath = env_copy.get('PYTHONPATH')
        if pythonpath:
            pythonpath = [pythonpath]
        else:
            pythonpath = []
        pythonpath = [self.executor_server.ansible_dir] + pythonpath
        env_copy['PYTHONPATH'] = os.path.pathsep.join(pythonpath)

        if playbook.trusted:
            opt_prefix = 'trusted'
        else:
            opt_prefix = 'untrusted'
        ro_paths = get_default(self.executor_server.config, 'executor',
                               '%s_ro_paths' % opt_prefix)
        rw_paths = get_default(self.executor_server.config, 'executor',
                               '%s_rw_paths' % opt_prefix)
        ro_paths = ro_paths.split(":") if ro_paths else []
        rw_paths = rw_paths.split(":") if rw_paths else []

        ro_paths.append(self.executor_server.ansible_dir)
        ro_paths.append(self.jobdir.ansible_root)
        ro_paths.append(self.jobdir.trusted_root)
        ro_paths.append(playbook.root)

        rw_paths.append(self.jobdir.ansible_cache_root)

        if self.executor_variables_file:
            ro_paths.append(self.executor_variables_file)

        secrets = {}
        if playbook.secrets_content:
            secrets[playbook.secrets] = playbook.secrets_content

        if wrapped:
            wrapper = self.executor_server.execution_wrapper
        else:
            wrapper = self.executor_server.connections.drivers['nullwrap']

        context = wrapper.getExecutionContext(ro_paths, rw_paths, secrets)

        popen = context.getPopen(
            work_dir=self.jobdir.work_root,
            ssh_auth_sock=env_copy.get('SSH_AUTH_SOCK'))

        env_copy['ANSIBLE_CONFIG'] = config_file
        # NOTE(pabelanger): Default HOME variable to jobdir.work_root, as it is
        # possible we don't bind mount current zuul user home directory.
        env_copy['HOME'] = self.jobdir.work_root

        with self.proc_lock:
            if self.aborted:
                return (self.RESULT_ABORTED, None)
            self.log.debug("Ansible command: ANSIBLE_CONFIG=%s %s",
                           config_file, " ".join(shlex.quote(c) for c in cmd))
            self.proc = popen(
                cmd,
                cwd=self.jobdir.work_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                env=env_copy,
            )

        syntax_buffer = []
        ret = None
        if timeout:
            watchdog = Watchdog(timeout, self._ansibleTimeout,
                                ("Ansible timeout exceeded",))
            watchdog.start()
        try:
            # Use manual idx instead of enumerate so that RESULT lines
            # don't count towards BUFFER_LINES_FOR_SYNTAX
            idx = 0
            for line in iter(self.proc.stdout.readline, b''):
                if line.startswith(b'RESULT'):
                    # TODO(mordred) Process result commands if sent
                    continue
                else:
                    idx += 1
                if idx < BUFFER_LINES_FOR_SYNTAX:
                    syntax_buffer.append(line)
                line = line[:1024].rstrip()
                self.log.debug("Ansible output: %s" % (line,))
            self.log.debug("Ansible output terminated")
            ret = self.proc.wait()
            self.log.debug("Ansible exit code: %s" % (ret,))
        finally:
            if timeout:
                watchdog.stop()
                self.log.debug("Stopped watchdog")
            self.log.debug("Stopped disk job killer")

        with self.proc_lock:
            self.proc = None

        if timeout and watchdog.timed_out:
            return (self.RESULT_TIMED_OUT, None)
        if ret == 3:
            # AnsibleHostUnreachable: We had a network issue connecting to
            # our zuul-worker.
            return (self.RESULT_UNREACHABLE, None)
        elif ret == -9:
            # Received abort request.
            return (self.RESULT_ABORTED, None)
        elif ret == 1:
            if syntax_buffer[0].startswith(b'ERROR!'):
                with open(self.jobdir.job_output_file, 'a') as job_output:
                    for line in syntax_buffer:
                        job_output.write("{now} | {line}\n".format(
                            now=datetime.datetime.now(),
                            line=line.decode('utf-8').rstrip()))
        elif ret == 4:
            # Ansible could not parse the yaml.
            self.log.debug("Ansible parse error")
            # TODO(mordred) If/when we rework use of logger in ansible-playbook
            # we'll want to change how this works to use that as well. For now,
            # this is what we need to do.
            # TODO(mordred) We probably want to put this into the json output
            # as well.
            with open(self.jobdir.job_output_file, 'a') as job_output:
                job_output.write("{now} | ANSIBLE PARSE ERROR\n".format(
                    now=datetime.datetime.now()))
                for line in syntax_buffer:
                    job_output.write("{now} | {line}\n".format(
                        now=datetime.datetime.now(),
                        line=line.decode('utf-8').rstrip()))
        elif ret == 250:
            # Unexpected error from ansible
            with open(self.jobdir.job_output_file, 'a') as job_output:
                job_output.write("{now} | UNEXPECTED ANSIBLE ERROR\n".format(
                    now=datetime.datetime.now()))
                found_marker = False
                for line in syntax_buffer:
                    if line.startswith(b'ERROR! Unexpected Exception'):
                        found_marker = True
                    if not found_marker:
                        continue
                    job_output.write("{now} | {line}\n".format(
                        now=datetime.datetime.now(),
                        line=line.decode('utf-8').rstrip()))

        return (self.RESULT_NORMAL, ret)

    def runAnsibleSetup(self, playbook):
        if self.executor_server.verbose:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible', '*', verbose, '-m', 'setup',
               '-a', 'gather_subset=!all']

        result, code = self.runAnsible(
            cmd=cmd, timeout=60, playbook=playbook,
            wrapped=False)
        self.log.debug("Ansible complete, result %s code %s" % (
            self.RESULT_MAP[result], code))
        return result, code

    def runAnsibleCleanup(self, playbook):
        # TODO(jeblair): This requires a bugfix in Ansible 2.4
        # Once this is used, increase the controlpersist timeout.
        return (self.RESULT_NORMAL, 0)

        if self.executor_server.verbose:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible', '*', verbose, '-m', 'meta',
               '-a', 'reset_connection']

        result, code = self.runAnsible(
            cmd=cmd, timeout=60, playbook=playbook,
            wrapped=False)
        self.log.debug("Ansible complete, result %s code %s" % (
            self.RESULT_MAP[result], code))
        return result, code

    def emitPlaybookBanner(self, playbook, step, phase, result=None):
        # This is used to print a header and a footer, respectively at the
        # beginning and the end of each playbook execution.
        # We are doing it from the executor rather than from a callback because
        # the parameters are not made available to the callback until it's too
        # late.
        phase = phase or ''
        trusted = playbook.trusted
        trusted = 'trusted' if trusted else 'untrusted'
        branch = playbook.branch
        playbook = playbook.canonical_name_and_path

        if phase and phase != 'run':
            phase = '{phase}-run'.format(phase=phase)
        phase = phase.upper()

        if result is not None:
            result = self.RESULT_MAP[result]
            msg = "{phase} {step} {result}: [{trusted} : {playbook}@{branch}]"
            msg = msg.format(phase=phase, step=step, result=result,
                             trusted=trusted, playbook=playbook, branch=branch)
        else:
            msg = "{phase} {step}: [{trusted} : {playbook}@{branch}]"
            msg = msg.format(phase=phase, step=step, trusted=trusted,
                             playbook=playbook, branch=branch)

        with open(self.jobdir.job_output_file, 'a') as job_output:
            job_output.write("{now} | {msg}\n".format(
                now=datetime.datetime.now(),
                msg=msg))

    def runAnsiblePlaybook(self, playbook, timeout, success=None,
                           phase=None, index=None):
        if self.executor_server.verbose:
            verbose = '-vvv'
        else:
            verbose = '-v'

        cmd = ['ansible-playbook', verbose, playbook.path]
        if playbook.secrets_content:
            cmd.extend(['-e', '@' + playbook.secrets])

        if success is not None:
            cmd.extend(['-e', 'zuul_success=%s' % str(bool(success))])

        if phase:
            cmd.extend(['-e', 'zuul_execution_phase=%s' % phase])

        if index is not None:
            cmd.extend(['-e', 'zuul_execution_phase_index=%s' % index])

        cmd.extend(['-e', 'zuul_execution_trusted=%s' % str(playbook.trusted)])
        cmd.extend([
            '-e',
            'zuul_execution_canonical_name_and_path=%s'
            % playbook.canonical_name_and_path])
        cmd.extend(['-e', 'zuul_execution_branch=%s' % str(playbook.branch)])

        if self.executor_variables_file is not None:
            cmd.extend(['-e@%s' % self.executor_variables_file])

        self.emitPlaybookBanner(playbook, 'START', phase)

        result, code = self.runAnsible(
            cmd=cmd, timeout=timeout, playbook=playbook)
        self.log.debug("Ansible complete, result %s code %s" % (
            self.RESULT_MAP[result], code))

        self.emitPlaybookBanner(playbook, 'END', phase, result=result)
        return result, code


class ExecutorMergeWorker(gear.TextWorker):
    def __init__(self, executor_server, *args, **kw):
        self.zuul_executor_server = executor_server
        super(ExecutorMergeWorker, self).__init__(*args, **kw)

    def handleNoop(self, packet):
        # Wait until the update queue is empty before responding
        while self.zuul_executor_server.update_queue.qsize():
            time.sleep(1)

        with self.zuul_executor_server.merger_lock:
            super(ExecutorMergeWorker, self).handleNoop(packet)


class ExecutorExecuteWorker(gear.TextWorker):
    def __init__(self, executor_server, *args, **kw):
        self.zuul_executor_server = executor_server
        super(ExecutorExecuteWorker, self).__init__(*args, **kw)

    def handleNoop(self, packet):
        # Delay our response to running a new job based on the number
        # of jobs we're currently running, in an attempt to spread
        # load evenly among executors.
        workers = len(self.zuul_executor_server.job_workers)
        delay = (workers ** 2) / 1000.0
        time.sleep(delay)
        return super(ExecutorExecuteWorker, self).handleNoop(packet)


class ExecutorServer(object):
    log = logging.getLogger("zuul.ExecutorServer")
    _job_class = AnsibleJob

    def __init__(self, config, connections={}, jobdir_root=None,
                 keep_jobdir=False, log_streaming_port=DEFAULT_FINGER_PORT):
        self.config = config
        self.keep_jobdir = keep_jobdir
        self.jobdir_root = jobdir_root
        # TODOv3(mordred): make the executor name more unique --
        # perhaps hostname+pid.
        self.hostname = get_default(self.config, 'executor', 'hostname',
                                    socket.gethostname())
        self.log_streaming_port = log_streaming_port
        self.merger_lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.verbose = False
        self.command_map = dict(
            stop=self.stop,
            pause=self.pause,
            unpause=self.unpause,
            graceful=self.graceful,
            verbose=self.verboseOn,
            unverbose=self.verboseOff,
            keep=self.keep,
            nokeep=self.nokeep,
        )

        self.statsd = get_statsd(config)
        self.merge_root = get_default(self.config, 'executor', 'git_dir',
                                      '/var/lib/zuul/executor-git')
        self.default_username = get_default(self.config, 'executor',
                                            'default_username', 'zuul')
        self.disk_limit_per_job = int(get_default(self.config, 'executor',
                                                  'disk_limit_per_job', 250))
        self.merge_email = get_default(self.config, 'merger', 'git_user_email')
        self.merge_name = get_default(self.config, 'merger', 'git_user_name')
        self.merge_speed_limit = get_default(
            config, 'merger', 'git_http_low_speed_limit', '1000')
        self.merge_speed_time = get_default(
            config, 'merger', 'git_http_low_speed_time', '30')
        execution_wrapper_name = get_default(self.config, 'executor',
                                             'execution_wrapper', 'bubblewrap')
        load_multiplier = float(get_default(self.config, 'executor',
                                            'load_multiplier', '2.5'))
        self.max_load_avg = multiprocessing.cpu_count() * load_multiplier
        self.accepting_work = False
        self.execution_wrapper = connections.drivers[execution_wrapper_name]

        self.connections = connections
        # This merger and its git repos are used to maintain
        # up-to-date copies of all the repos that are used by jobs, as
        # well as to support the merger:cat functon to supply
        # configuration information to Zuul when it starts.
        self.merger = self._getMerger(self.merge_root)
        self.update_queue = DeduplicateQueue()

        state_dir = get_default(self.config, 'executor', 'state_dir',
                                '/var/lib/zuul', expand_user=True)
        path = os.path.join(state_dir, 'executor.socket')
        self.command_socket = commandsocket.CommandSocket(path)
        ansible_dir = os.path.join(state_dir, 'ansible')
        self.ansible_dir = ansible_dir
        if os.path.exists(ansible_dir):
            shutil.rmtree(ansible_dir)

        zuul_dir = os.path.join(ansible_dir, 'zuul')
        plugin_dir = os.path.join(zuul_dir, 'ansible')

        os.makedirs(plugin_dir, mode=0o0755)

        self.library_dir = os.path.join(plugin_dir, 'library')
        self.action_dir = os.path.join(plugin_dir, 'action')
        self.callback_dir = os.path.join(plugin_dir, 'callback')
        self.lookup_dir = os.path.join(plugin_dir, 'lookup')
        self.filter_dir = os.path.join(plugin_dir, 'filter')

        _copy_ansible_files(zuul.ansible, plugin_dir)

        # We're copying zuul.ansible.* into a directory we are going
        # to add to pythonpath, so our plugins can "import
        # zuul.ansible".  But we're not installing all of zuul, so
        # create a __init__.py file for the stub "zuul" module.
        with open(os.path.join(zuul_dir, '__init__.py'), 'w'):
            pass

        self.job_workers = {}
        self.disk_accountant = DiskAccountant(self.jobdir_root,
                                              self.disk_limit_per_job,
                                              self.stopJobDiskFull,
                                              self.merge_root)

    def _getMerger(self, root, logger=None):
        if root != self.merge_root:
            cache_root = self.merge_root
        else:
            cache_root = None
        return zuul.merger.merger.Merger(
            root, self.connections, self.merge_email, self.merge_name,
            self.merge_speed_limit, self.merge_speed_time, cache_root, logger)

    def start(self):
        self._running = True
        self._command_running = True
        server = self.config.get('gearman', 'server')
        port = get_default(self.config, 'gearman', 'port', 4730)
        ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')
        self.merger_worker = ExecutorMergeWorker(self, 'Zuul Executor Merger')
        self.merger_worker.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.executor_worker = ExecutorExecuteWorker(
            self, 'Zuul Executor Server')
        self.executor_worker.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for server")
        self.merger_worker.waitForServer()
        self.executor_worker.waitForServer()
        self.log.debug("Registering")
        self.register()

        self.log.debug("Starting command processor")
        self.command_socket.start()
        self.command_thread = threading.Thread(target=self.runCommand,
                                               name='command')
        self.command_thread.daemon = True
        self.command_thread.start()

        self.log.debug("Starting worker")
        self.update_thread = threading.Thread(target=self._updateLoop,
                                              name='update')
        self.update_thread.daemon = True
        self.update_thread.start()
        self.merger_thread = threading.Thread(target=self.run_merger,
                                              name='merger')
        self.merger_thread.daemon = True
        self.merger_thread.start()
        self.executor_thread = threading.Thread(target=self.run_executor,
                                                name='executor')
        self.executor_thread.daemon = True
        self.executor_thread.start()
        self.governor_stop_event = threading.Event()
        self.governor_thread = threading.Thread(target=self.run_governor,
                                                name='governor')
        self.governor_thread.daemon = True
        self.governor_thread.start()
        self.disk_accountant.start()

    def register(self):
        self.register_work()
        self.executor_worker.registerFunction("executor:stop:%s" %
                                              self.hostname)
        self.merger_worker.registerFunction("merger:merge")
        self.merger_worker.registerFunction("merger:cat")
        self.merger_worker.registerFunction("merger:refstate")

    def register_work(self):
        if self._running:
            self.accepting_work = True
            self.executor_worker.registerFunction("executor:execute")

    def unregister_work(self):
        self.accepting_work = False
        self.executor_worker.unRegisterFunction("executor:execute")

    def stop(self):
        self.log.debug("Stopping")
        self.disk_accountant.stop()
        # The governor can change function registration, so make sure
        # it has stopped.
        self.governor_stop_event.set()
        self.governor_thread.join()
        # Stop accepting new jobs
        self.merger_worker.setFunctions([])
        self.executor_worker.setFunctions([])
        # Tell the executor worker to abort any jobs it just accepted,
        # and grab the list of currently running job workers.
        with self.run_lock:
            self._running = False
            self._command_running = False
            workers = list(self.job_workers.values())
        self.command_socket.stop()

        for job_worker in workers:
            try:
                job_worker.stop()
            except Exception:
                self.log.exception("Exception sending stop command "
                                   "to worker:")
        for job_worker in workers:
            try:
                job_worker.wait()
            except Exception:
                self.log.exception("Exception waiting for worker "
                                   "to stop:")

        # Now that we aren't accepting any new jobs, and all of the
        # running jobs have stopped, tell the update processor to
        # stop.
        self.update_queue.put(None)

        # All job results should have been sent by now, shutdown the
        # gearman workers.
        self.merger_worker.shutdown()
        self.executor_worker.shutdown()

        if self.statsd:
            base_key = 'zuul.executor.%s' % self.hostname
            self.statsd.gauge(base_key + '.load_average', 0)
            self.statsd.gauge(base_key + '.running_builds', 0)

        self.log.debug("Stopped")

    def join(self):
        self.governor_thread.join()
        self.update_thread.join()
        self.merger_thread.join()
        self.executor_thread.join()

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
        self.verbose = True

    def verboseOff(self):
        self.verbose = False

    def keep(self):
        self.keep_jobdir = True

    def nokeep(self):
        self.keep_jobdir = False

    def runCommand(self):
        while self._command_running:
            try:
                command = self.command_socket.get().decode('utf8')
                if command != '_stop':
                    self.command_map[command]()
            except Exception:
                self.log.exception("Exception while processing command")

    def _updateLoop(self):
        while True:
            try:
                self._innerUpdateLoop()
            except StopException:
                return
            except Exception:
                self.log.exception("Exception in update thread:")

    def _innerUpdateLoop(self):
        # Inside of a loop that keeps the main repositories up to date
        task = self.update_queue.get()
        if task is None:
            # We are asked to stop
            raise StopException()
        with self.merger_lock:
            self.log.info("Updating repo %s/%s" % (
                task.connection_name, task.project_name))
            self.merger.updateRepo(task.connection_name, task.project_name)
            self.log.debug("Finished updating repo %s/%s" %
                           (task.connection_name, task.project_name))
        task.setComplete()

    def update(self, connection_name, project_name):
        # Update a repository in the main merger
        task = UpdateTask(connection_name, project_name)
        task = self.update_queue.put(task)
        return task

    def run_merger(self):
        self.log.debug("Starting merger listener")
        while self._running:
            try:
                job = self.merger_worker.getJob()
                try:
                    self.mergerJobDispatch(job)
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(
                        traceback.format_exc().encode('utf8'))
            except gear.InterruptedError:
                pass
            except Exception:
                self.log.exception("Exception while getting job")

    def mergerJobDispatch(self, job):
        with self.run_lock:
            if job.name == 'merger:cat':
                self.log.debug("Got cat job: %s" % job.unique)
                self.cat(job)
            elif job.name == 'merger:merge':
                self.log.debug("Got merge job: %s" % job.unique)
                self.merge(job)
            elif job.name == 'merger:refstate':
                self.log.debug("Got refstate job: %s" % job.unique)
                self.refstate(job)
            else:
                self.log.error("Unable to handle job %s" % job.name)
                job.sendWorkFail()

    def run_executor(self):
        self.log.debug("Starting executor listener")
        while self._running:
            try:
                job = self.executor_worker.getJob()
                try:
                    self.executorJobDispatch(job)
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(
                        traceback.format_exc().encode('utf8'))
            except gear.InterruptedError:
                pass
            except Exception:
                self.log.exception("Exception while getting job")

    def executorJobDispatch(self, job):
        with self.run_lock:
            if not self._running:
                job.sendWorkFail()
                return
            if job.name == 'executor:execute':
                self.log.debug("Got execute job: %s" % job.unique)
                self.executeJob(job)
            elif job.name.startswith('executor:stop'):
                self.log.debug("Got stop job: %s" % job.unique)
                self.stopJob(job)
            else:
                self.log.error("Unable to handle job %s" % job.name)
                job.sendWorkFail()

    def executeJob(self, job):
        if self.statsd:
            base_key = 'zuul.executor.%s' % self.hostname
            self.statsd.incr(base_key + '.builds')
        self.job_workers[job.unique] = self._job_class(self, job)
        self.job_workers[job.unique].run()

    def run_governor(self):
        while not self.governor_stop_event.wait(30):
            try:
                self.manageLoad()
            except Exception:
                self.log.exception("Exception in governor thread:")

    def manageLoad(self):
        ''' Apply some heuristics to decide whether or not we should
            be askign for more jobs '''
        load_avg = os.getloadavg()[0]
        if self.accepting_work:
            # Don't unregister if we don't have any active jobs.
            if load_avg > self.max_load_avg and self.job_workers:
                self.log.info(
                    "Unregistering due to high system load {} > {}".format(
                        load_avg, self.max_load_avg))
                self.unregister_work()
        elif load_avg <= self.max_load_avg:
            self.log.info(
                "Re-registering as load is within limits {} <= {}".format(
                    load_avg, self.max_load_avg))
            self.register_work()
        if self.statsd:
            base_key = 'zuul.executor.%s' % self.hostname
            self.statsd.gauge(base_key + '.load_average',
                              int(load_avg * 100))
            self.statsd.gauge(base_key + '.running_builds',
                              len(self.job_workers))

    def finishJob(self, unique):
        del(self.job_workers[unique])

    def stopJobDiskFull(self, jobdir):
        unique = os.path.basename(jobdir)
        self.stopJobByUnique(unique, reason=AnsibleJob.RESULT_DISK_FULL)

    def stopJob(self, job):
        try:
            args = json.loads(job.arguments)
            self.log.debug("Stop job with arguments: %s" % (args,))
            unique = args['uuid']
            self.stopJobByUnique(unique)
        finally:
            job.sendWorkComplete()

    def stopJobByUnique(self, unique, reason=None):
        job_worker = self.job_workers.get(unique)
        if not job_worker:
            self.log.debug("Unable to find worker for job %s" % (unique,))
            return
        try:
            job_worker.stop(reason)
        except Exception:
            self.log.exception("Exception sending stop command "
                               "to worker:")

    def cat(self, job):
        args = json.loads(job.arguments)
        task = self.update(args['connection'], args['project'])
        task.wait()
        with self.merger_lock:
            files = self.merger.getFiles(args['connection'], args['project'],
                                         args['branch'], args['files'],
                                         args.get('dirs', []))
        result = dict(updated=True,
                      files=files)
        job.sendWorkComplete(json.dumps(result))

    def refstate(self, job):
        args = json.loads(job.arguments)
        with self.merger_lock:
            success, repo_state = self.merger.getRepoState(args['items'])
        result = dict(updated=success,
                      repo_state=repo_state)
        job.sendWorkComplete(json.dumps(result))

    def merge(self, job):
        args = json.loads(job.arguments)
        with self.merger_lock:
            ret = self.merger.mergeChanges(args['items'], args.get('files'),
                                           args.get('dirs', []),
                                           args.get('repo_state'))
        result = dict(merged=(ret is not None))
        if ret is None:
            result['commit'] = result['files'] = result['repo_state'] = None
        else:
            (result['commit'], result['files'], result['repo_state'],
             recent) = ret
        job.sendWorkComplete(json.dumps(result))
