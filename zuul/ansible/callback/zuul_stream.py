# Copyright 2017 Red Hat, Inc.
#
# Zuul is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Zuul is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

# This is not needed in python3 - but it is needed in python2 because there
# is a json module in ansible.plugins.callback and python2 gets confused.
# Easy local testing with ansible-playbook is handy when hacking on zuul_stream
# so just put in the __future__ statement.
from __future__ import absolute_import

import datetime
import logging
import json
import os
import socket
import threading
import time
import uuid

from ansible.plugins.callback import default

LOG_STREAM_PORT = 19885


def linesplit(socket):
    buff = socket.recv(4096).decode("utf-8")
    buffering = True
    while buffering:
        if "\n" in buff:
            (line, buff) = buff.split("\n", 1)
            yield line + "\n"
        else:
            more = socket.recv(4096).decode("utf-8")
            if not more:
                buffering = False
            else:
                buff += more
    if buff:
        yield buff


def zuul_filter_result(result):
    """Remove keys from shell/command output.

    Zuul streams stdout into the log above, so including stdout and stderr
    in the result dict that ansible displays in the logs is duplicate
    noise. We keep stdout in the result dict so that other callback plugins
    like ARA could also have access to it. But drop them here.

    Remove changed so that we don't show a bunch of "changed" titles
    on successful shell tasks, since that doesn't make sense from a Zuul
    POV. The super class treats missing "changed" key as False.

    Remove cmd because most of the script content where people want to
    see the script run is run with -x. It's possible we may want to revist
    this to be smarter about when we remove it - like, only remove it
    if it has an embedded newline - so that for normal 'simple' uses
    of cmd it'll echo what the command was for folks.
    """

    stdout = result.pop('stdout', '')
    stdout_lines = result.pop('stdout_lines', [])
    if not stdout_lines and stdout:
        stdout_lines = stdout.split('\n')

    for key in ('changed', 'cmd', 'zuul_log_id', 'invocation',
                'stderr', 'stderr_lines'):
        result.pop(key, None)
    return stdout_lines


class CallbackModule(default.CallbackModule):

    '''
    This is the Zuul streaming callback. It's based on the default
    callback plugin, but streams results from shell commands.
    '''

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'zuul_stream'

    def __init__(self):

        super(CallbackModule, self).__init__()
        self._task = None
        self._daemon_running = False
        self._play = None
        self._streamers = []
        self.configure_logger()
        self._items_done = False
        self._deferred_result = None
        self._playbook_name = None

    def configure_logger(self):
        # ansible appends timestamp, user and pid to the log lines emitted
        # to the log file. We're doing other things though, so we don't want
        # this.
        path = os.environ['ZUUL_JOB_OUTPUT_FILE']
        if self._display.verbosity > 2:
            level = logging.DEBUG
        else:
            level = logging.INFO
        logging.basicConfig(filename=path, level=level, format='%(message)s')
        self._logger = logging.getLogger('zuul.executor.ansible')

    def _log(self, msg, ts=None, job=True, executor=False, debug=False):
        if job:
            now = ts or datetime.datetime.now()
            self._logger.info("{now} | {msg}".format(now=now, msg=msg))
        if executor:
            if debug:
                self._display.vvv(msg)
            else:
                self._display.display(msg)

    def _read_log(self, host, ip, log_id, task_name, hosts):
        self._log("[%s] Starting to log %s for task %s"
                  % (host, log_id, task_name), job=False, executor=True)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                s.connect((ip, LOG_STREAM_PORT))
            except Exception:
                self._log("[%s] Waiting on logger" % host,
                          executor=True, debug=True)
                time.sleep(0.1)
                continue
            msg = "%s\n" % log_id
            s.send(msg.encode("utf-8"))
            for line in linesplit(s):
                if "[Zuul] Task exit code" in line:
                    return
                else:
                    ts, ln = line.split(' | ', 1)
                    ln = ln.strip()

                    self._log("%s | %s " % (host, ln), ts=ts)

    def v2_playbook_on_start(self, playbook):
        self._playbook_name = os.path.splitext(playbook._file_name)[0]

    def v2_playbook_on_include(self, included_file):
        for host in included_file._hosts:
            self._log("{host} | included: {filename}".format(
                host=host.name,
                filename=included_file._filename))

    def _emit_playbook_banner(self):
        # Get the hostvars from just one host - the vars we're looking for will
        # be identical on all of them
        hostvars = next(iter(self._play._variable_manager._hostvars.values()))
        self._playbook_name = None

        phase = hostvars.get('zuul_execution_phase', '')
        playbook = hostvars.get('zuul_execution_canonical_name_and_path')
        trusted = hostvars.get('zuul_execution_trusted')
        trusted = 'trusted' if trusted == "True" else 'untrusted'
        branch = hostvars.get('zuul_execution_branch')

        if phase and phase != 'run':
            phase = '{phase}-run'.format(phase=phase)
        phase = phase.upper()

        self._log("{phase} [{trusted} : {playbook}@{branch}]".format(
            trusted=trusted, phase=phase, playbook=playbook, branch=branch))

    def v2_playbook_on_play_start(self, play):
        self._play = play

        # We can't fill in this information until the first play
        if self._playbook_name:
            self._emit_playbook_banner()

        # Log an extra blank line to get space before each play
        self._log("")

        # the name of a play defaults to the hosts string
        name = play.get_name().strip()
        msg = u"PLAY [{name}]".format(name=name)

        self._log(msg)
        # Log an extra blank line to get space after each play
        self._log("")

    def v2_playbook_on_task_start(self, task, is_conditional):
        self._task = task

        if self._play.strategy != 'free':
            task_name = self._print_task_banner(task)
        if task.action == 'command':
            log_id = uuid.uuid4().hex
            task.args['zuul_log_id'] = log_id
            play_vars = self._play._variable_manager._hostvars

            hosts = self._get_task_hosts(task)
            for host in hosts:
                if host in ('localhost', '127.0.0.1'):
                    # Don't try to stream from localhost
                    continue
                ip = play_vars[host].get(
                    'ansible_host', play_vars[host].get(
                        'ansible_inventory_host'))
                if ip in ('localhost', '127.0.0.1'):
                    # Don't try to stream from localhost
                    continue
                streamer = threading.Thread(
                    target=self._read_log, args=(
                        host, ip, log_id, task_name, hosts))
                streamer.daemon = True
                streamer.start()
                self._streamers.append(streamer)

    def _stop_streamers(self):
        while True:
            if not self._streamers:
                break
            streamer = self._streamers.pop()
            streamer.join(30)
            if streamer.is_alive():
                msg = "[Zuul] Log Stream did not terminate"
                self._log(msg, job=True, executor=True)

    def _process_result_for_localhost(self, result, is_task=True):
        result_dict = dict(result._result)
        localhost_names = ('localhost', '127.0.0.1')
        is_localhost = False
        task_host = result._host.get_name()
        delegated_vars = result_dict.get('_ansible_delegated_vars', None)
        if delegated_vars:
            delegated_host = delegated_vars['ansible_host']
            if delegated_host in localhost_names:
                is_localhost = True
        elif result._task._variable_manager is None:
            # Handle fact gathering which doens't have a variable manager
            if task_host == 'localhost':
                is_localhost = True
        else:
            task_hostvars = result._task._variable_manager._hostvars[task_host]
            if task_hostvars.get('ansible_host', task_hostvars.get(
                    'ansible_inventory_host')) in localhost_names:
                is_localhost = True

        if not is_localhost and is_task:
            self._stop_streamers()
        if result._task.action in ('command', 'shell'):
            stdout_lines = zuul_filter_result(result_dict)
            if is_localhost:
                for line in stdout_lines:
                    hostname = self._get_hostname(result)
                    self._log("%s | %s " % (hostname, line.strip()))

    def v2_runner_on_failed(self, result, ignore_errors=False):
        result_dict = dict(result._result)

        self._handle_exception(result_dict)

        if result_dict.get('msg') == 'All items completed':
            result_dict['status'] = 'ERROR'
            self._deferred_result = result_dict
            return

        self._process_result_for_localhost(result)

        if result._task.loop and 'results' in result_dict:
            # items have their own events
            pass
        else:
            self._log_message(
                result=result, status='ERROR', result_dict=result_dict)
        if ignore_errors:
            self._log_message(result, "Ignoring Errors", status="ERROR")
        # Log an extra blank line to get space after each task
        self._log("")

    def v2_runner_on_ok(self, result):
        if (self._play.strategy == 'free'
                and self._last_task_banner != result._task._uuid):
            self._print_task_banner(result._task)

        if result._task.action in ('include', 'include_role', 'setup'):
            return

        result_dict = dict(result._result)

        self._clean_results(result_dict, result._task.action)
        if '_zuul_nolog_return' in result_dict:
            # We have a custom zuul module that doesn't want the parameters
            # from its returned splatted to stdout. This is typically for
            # modules that are collecting data to be displayed some other way.
            for key in result_dict.keys():
                if key != 'changed':
                    result_dict.pop(key)

        if result_dict.get('changed', False):
            status = 'changed'
        else:
            status = 'ok'

        if (result_dict.get('msg') == 'All items completed'
                and not self._items_done):
            result_dict['status'] = status
            self._deferred_result = result_dict
            return

        if not result._task.loop:
            self._process_result_for_localhost(result)
        else:
            self._items_done = False

        self._handle_warnings(result_dict)

        if result._task.loop and 'results' in result_dict:
            # items have their own events
            pass

        elif result._task.action not in ('command', 'shell'):
            if 'msg' in result_dict:
                self._log_message(msg=result_dict['msg'],
                                  result=result, status=status)
            else:
                self._log_message(
                    result=result,
                    status=status)
        elif 'results' in result_dict:
            for res in result_dict['results']:
                self._log_message(
                    result,
                    "Runtime: {delta} Start: {start} End: {end}".format(**res))
        elif result_dict.get('msg') == 'All items completed':
            self._log_message(result, result_dict['msg'])
        else:
            self._log_message(
                result,
                "Runtime: {delta} Start: {start} End: {end}".format(
                    **result_dict))
        # Log an extra blank line to get space after each task
        self._log("")

    def v2_runner_item_on_ok(self, result):
        result_dict = dict(result._result)
        self._process_result_for_localhost(result, is_task=False)

        if result_dict.get('changed', False):
            status = 'changed'
        else:
            status = 'ok'

        if result._task.action not in ('command', 'shell'):
            self._log_message(
                result=result,
                msg="Item: {item}".format(item=result_dict['item']),
                status=status)
        else:
            self._log_message(
                result,
                "Item: {item} Runtime: {delta}"
                " Start: {start} End: {end}".format(**result_dict))

        if self._deferred_result:
            self._process_deferred(result)
        # Log an extra blank line to get space after each task
        self._log("")

    def v2_runner_item_on_failed(self, result):
        result_dict = dict(result._result)
        self._process_result_for_localhost(result, is_task=False)

        if result._task.action not in ('command', 'shell'):
            self._log_message(
                result=result,
                msg="Item: {item}".format(item=result_dict['item']),
                status='ERROR',
                result_dict=result_dict)
        else:
            self._log_message(
                result,
                "Item: {item} Runtime: {delta}"
                " Start: {start} End: {end}".format(**result_dict))

        if self._deferred_result:
            self._process_deferred(result)
        # Log an extra blank line to get space after each task
        self._log("")

    def v2_playbook_on_stats(self, stats):

        self._log("PLAY RECAP")

        hosts = sorted(stats.processed.keys())
        for host in hosts:
            t = stats.summarize(host)
            self._log(
                "{host} |"
                " ok: {ok}"
                " changed: {changed}"
                " unreachable: {unreachable}"
                " failed: {failures}".format(host=host, **t))

        # Add a spacer line after the stats so that there will be a line
        # between each playbook
        self._log("")

    def _process_deferred(self, result):
        self._items_done = True
        result_dict = self._deferred_result
        self._deferred_result = None

        self._log_message(
            result, "All items complete",
            status=result_dict['status'])

    def _print_task_banner(self, task):

        task_name = task.get_name().strip()

        if task.loop:
            task_type = 'LOOP'
        else:
            task_type = 'TASK'

        # TODO(mordred) With the removal of printing task args, do we really
        # want to keep doing this section?
        task_args = task.args.copy()
        is_shell = task_args.pop('_uses_shell', False)
        if is_shell and task_name == 'command':
            task_name = 'shell'
        raw_params = task_args.pop('_raw_params', '').split('\n')
        # If there's just a single line, go ahead and print it
        if len(raw_params) == 1 and task_name in ('shell', 'command'):
            task_name = '{name}: {command}'.format(
                name=task_name, command=raw_params[0])

        msg = "{task_type} [{task}]".format(
            task_type=task_type,
            task=task_name)
        self._log(msg)
        return task

    def _get_task_hosts(self, task):
        # If this task has as delegate to, we don't care about the play hosts,
        # we care about the task's delegate target.
        delegate_to = task.delegate_to
        if delegate_to:
            return [delegate_to]
        hosts = self._play.hosts
        if 'all' in hosts:
            # NOTE(jamielennox): play.hosts is purely the list of hosts
            # that was provided not interpretted by inventory. We don't
            # have inventory access here but we can assume that 'all' is
            # everything in hostvars.
            play_vars = self._play._variable_manager._hostvars
            hosts = play_vars.keys()
        return hosts

    def _dump_result_dict(self, result_dict):
        result_dict = result_dict.copy()
        for key in list(result_dict.keys()):
            if key.startswith('_ansible'):
                del result_dict[key]
        zuul_filter_result(result_dict)
        return result_dict

    def _log_message(self, result, msg=None, status="ok", result_dict=None):
        hostname = self._get_hostname(result)
        if result_dict:
            result_dict = self._dump_result_dict(result_dict)
        if result._task.no_log:
            self._log("{host} | {msg}".format(
                host=hostname,
                msg="Output suppressed because no_log was given"))
            return
        if not msg and set(result_dict.keys()) == set(['msg', 'failed']):
            msg = result_dict['msg']
            result_dict = None
        if msg:
            msg_lines = msg.strip().split('\n')
            if len(msg_lines) > 1:
                self._log("{host} | {status}:".format(
                    host=hostname, status=status))
                for msg_line in msg_lines:
                    self._log("{host} | {msg_line}".format(
                        host=hostname, msg_line=msg_line))
            else:
                self._log("{host} | {status}: {msg}".format(
                    host=hostname, status=status, msg=msg))
        else:
            self._log("{host} | {status}".format(
                host=hostname, status=status, msg=msg))
        if result_dict:
            result_string = json.dumps(result_dict, indent=2, sort_keys=True)
            for line in result_string.split('\n'):
                self._log("{host} | {line}".format(host=hostname, line=line))

    def _get_hostname(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if delegated_vars:
            return "{host} -> {delegated_host}".format(
                host=result._host.get_name(),
                delegated_host=delegated_vars['ansible_host'])
        else:
            return result._host.get_name()
