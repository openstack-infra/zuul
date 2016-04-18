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
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import traceback

import gear
import yaml


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
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = True
        self.thread.start()

    def register(self):
        self.worker.registerFunction("node-assign:zuul")

    def stop(self):
        self.log.debug("Stopping")
        self._running = False
        self.worker.shutdown()
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
        data = dict(manager=self.hostname)
        job.sendWorkData(json.dumps(data))
        job.sendWorkComplete()

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
