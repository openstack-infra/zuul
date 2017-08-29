# (c) 2016, Matt Martz <matt@sivel.net>
# (c) 2017, Red Hat, Inc.
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

# Copy of github.com/ansible/ansible/lib/ansible/plugins/callback/json.py
# We need to run as a secondary callback not a stdout and we need to control
# the output file location via a zuul environment variable similar to how we
# do in zuul_stream.
# Subclassing wreaks havoc on the module loader and namepsaces
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os

from ansible.plugins.callback import CallbackBase
try:
    # It's here in 2.4
    from ansible.vars import strip_internal_keys
except ImportError:
    # It's here in 2.3
    from ansible.vars.manager import strip_internal_keys

from zuul.ansible import logconfig


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    # aggregate means we can be loaded and not be the stdout plugin
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'zuul_json'

    def __init__(self, display=None):
        super(CallbackModule, self).__init__(display)
        self.results = []
        self.output = []
        self.playbook = {}
        logging_config = logconfig.load_job_config(
            os.environ['ZUUL_JOB_LOG_CONFIG'])

        self.output_path = os.path.splitext(
            logging_config.job_output_file)[0] + '.json'

        # For now, just read in the old file and write it all out again
        # This may well not scale from a memory perspective- but let's see how
        # it goes.
        if os.path.exists(self.output_path):
            self.output = json.load(open(self.output_path, 'r'))
        self._playbook_name = None

    def _new_playbook(self, play):
        # Get the hostvars from just one host - the vars we're looking for will
        # be identical on all of them
        hostvars = next(iter(play._variable_manager._hostvars.values()))
        self._playbook_name = None

        # TODO(mordred) For now, protect specific variable lookups to make it
        # not absurdly strange to run local tests with the callback plugin
        # enabled. Remove once we have a "run playbook like zuul runs playbook"
        # tool.
        phase = hostvars.get('zuul_execution_phase')
        index = hostvars.get('zuul_execution_phase_index')
        playbook = hostvars.get('zuul_execution_canonical_name_and_path')
        trusted = hostvars.get('zuul_execution_trusted')
        trusted = True if trusted == "True" else False
        branch = hostvars.get('zuul_execution_branch')

        self.playbook['playbook'] = playbook
        self.playbook['phase'] = phase
        self.playbook['index'] = index
        self.playbook['trusted'] = trusted
        self.playbook['branch'] = branch

    def _new_play(self, play):
        return {
            'play': {
                'name': play.name,
                'id': str(play._uuid),
            },
            'tasks': []
        }

    def _new_task(self, task):
        return {
            'task': {
                'name': task.name,
                'id': str(task._uuid)
            },
            'hosts': {}
        }

    def v2_playbook_on_start(self, playbook):
        self._playbook_name = os.path.splitext(playbook._file_name)[0]

    def v2_playbook_on_play_start(self, play):
        if self._playbook_name:
            self._new_playbook(play)

        self.results.append(self._new_play(play))

    def v2_playbook_on_task_start(self, task, is_conditional):
        self.results[-1]['tasks'].append(self._new_task(task))

    def v2_runner_on_ok(self, result, **kwargs):
        host = result._host
        if result._result.get('_ansible_no_log', False):
            self.results[-1]['tasks'][-1]['hosts'][host.name] = dict(
                censored="the output has been hidden due to the fact that"
                         " 'no_log: true' was specified for this result")
        else:
            clean_result = strip_internal_keys(result._result)
            self.results[-1]['tasks'][-1]['hosts'][host.name] = clean_result

    def v2_playbook_on_stats(self, stats):
        """Display info about playbook statistics"""
        hosts = sorted(stats.processed.keys())

        summary = {}
        for h in hosts:
            s = stats.summarize(h)
            summary[h] = s

        self.playbook['plays'] = self.results
        self.playbook['stats'] = summary
        self.output.append(self.playbook)

        json.dump(self.output, open(self.output_path, 'w'),
                  indent=4, sort_keys=True, separators=(',', ': '))

    v2_runner_on_failed = v2_runner_on_ok
    v2_runner_on_unreachable = v2_runner_on_ok
    v2_runner_on_skipped = v2_runner_on_ok
