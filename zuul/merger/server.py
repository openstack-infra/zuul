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
import threading
import traceback

import gear

from zuul.lib import commandsocket
from zuul.lib.config import get_default
from zuul.merger import merger


COMMANDS = ['stop']


class MergeServer(object):
    log = logging.getLogger("zuul.MergeServer")

    def __init__(self, config, connections={}):
        self.config = config

        merge_root = get_default(self.config, 'merger', 'git_dir',
                                 '/var/lib/zuul/merger-git')
        merge_email = get_default(self.config, 'merger', 'git_user_email')
        merge_name = get_default(self.config, 'merger', 'git_user_name')
        speed_limit = get_default(
            config, 'merger', 'git_http_low_speed_limit', '1000')
        speed_time = get_default(
            config, 'merger', 'git_http_low_speed_time', '30')
        self.merger = merger.Merger(
            merge_root, connections, merge_email, merge_name, speed_limit,
            speed_time)
        self.command_map = dict(
            stop=self.stop)
        command_socket = get_default(
            self.config, 'merger', 'command_socket',
            '/var/lib/zuul/merger.socket')
        self.command_socket = commandsocket.CommandSocket(command_socket)

    def start(self):
        self._running = True
        self._command_running = True
        server = self.config.get('gearman', 'server')
        port = get_default(self.config, 'gearman', 'port', 4730)
        ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')
        self.worker = gear.TextWorker('Zuul Merger')
        self.worker.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for server")
        self.worker.waitForServer()
        self.log.debug("Registering")
        self.register()
        self.log.debug("Starting command processor")
        self.command_socket.start()
        self.command_thread = threading.Thread(
            target=self.runCommand, name='command')
        self.command_thread.daemon = True
        self.command_thread.start()

        self.log.debug("Starting worker")
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("merger:merge")
        self.worker.registerFunction("merger:cat")
        self.worker.registerFunction("merger:refstate")

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self._command_running = False
        self.command_socket.stop()
        self.worker.shutdown()
        self.log.debug("Stopped")

    def join(self):
        self.thread.join()

    def runCommand(self):
        while self._command_running:
            try:
                command = self.command_socket.get().decode('utf8')
                if command != '_stop':
                    self.command_map[command]()
            except Exception:
                self.log.exception("Exception while processing command")

    def run(self):
        self.log.debug("Starting merge listener")
        while self._running:
            try:
                job = self.worker.getJob()
                try:
                    if job.name == 'merger:merge':
                        self.log.debug("Got merge job: %s" % job.unique)
                        self.merge(job)
                    elif job.name == 'merger:cat':
                        self.log.debug("Got cat job: %s" % job.unique)
                        self.cat(job)
                    elif job.name == 'merger:refstate':
                        self.log.debug("Got refstate job: %s" % job.unique)
                        self.refstate(job)
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

    def merge(self, job):
        args = json.loads(job.arguments)
        ret = self.merger.mergeChanges(
            args['items'], args.get('files'),
            args.get('dirs'), args.get('repo_state'))
        result = dict(merged=(ret is not None))
        if ret is None:
            result['commit'] = result['files'] = result['repo_state'] = None
        else:
            (result['commit'], result['files'], result['repo_state'],
             recent) = ret
        job.sendWorkComplete(json.dumps(result))

    def refstate(self, job):
        args = json.loads(job.arguments)

        success, repo_state = self.merger.getRepoState(args['items'])
        result = dict(updated=success,
                      repo_state=repo_state)
        job.sendWorkComplete(json.dumps(result))

    def cat(self, job):
        args = json.loads(job.arguments)
        self.merger.updateRepo(args['connection'], args['project'])
        files = self.merger.getFiles(args['connection'], args['project'],
                                     args['branch'], args['files'],
                                     args.get('dirs'))
        result = dict(updated=True,
                      files=files)
        job.sendWorkComplete(json.dumps(result))
