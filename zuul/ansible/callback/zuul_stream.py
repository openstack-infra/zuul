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

import datetime
import logging
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

    for key in ('changed', 'cmd', 'zuul_log_id',
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
                  % (host, log_id, task_name), executor=True)
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

    def v2_playbook_on_play_start(self, play):
        self._play = play
        name = play.get_name().strip()
        if not name:
            msg = u"PLAY"
        else:
            msg = u"PLAY [{playbook} : {name}]".format(
                playbook=self._playbook_name, name=name)

        self._log(msg)

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

    def _process_result_for_localhost(self, result):
        is_localhost = False
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if delegated_vars:
            delegated_host = delegated_vars['ansible_host']
            if delegated_host in ('localhost', '127.0.0.1'):
                is_localhost = True

        if not is_localhost:
            self._stop_streamers()
        if result._task.action in ('command', 'shell'):
            stdout_lines = zuul_filter_result(result._result)
        if is_localhost:
            for line in stdout_lines:
                ts, ln = (x.strip() for x in line.split(' | ', 1))
                self._log("localhost | %s " % ln, ts=ts)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._process_result_for_localhost(result)
        self._handle_exception(result._result)

        if result._task.loop and 'results' in result._result:
            self._process_items(result)
        else:
            self._log_message(
                result=result,
                msg="Results: => {results}".format(
                    results=self._dump_results(result._result)),
                status='ERROR')
        if ignore_errors:
            self._log_message(result, "Ignoring Errors", status="ERROR")

    def v2_runner_on_ok(self, result):
        if (self._play.strategy == 'free'
                and self._last_task_banner != result._task._uuid):
            self._print_task_banner(result._task)

        self._clean_results(result._result, result._task.action)
        self._process_result_for_localhost(result)

        if result._task.action in ('include', 'include_role'):
            return

        if result._result.get('changed', False):
            status = 'changed'
        else:
            status = 'ok'

        if result._task.loop and 'results' in result._result:
            self._process_items(result)

        self._handle_warnings(result._result)

        if result._task.loop and 'results' in result._result:
            self._process_items(result)
        elif result._task.action not in ('command', 'shell'):
            self._log_message(
                result=result,
                msg="Results: => {results}".format(
                    results=self._dump_results(result._result)),
                status=status)
        else:
            self._log_message(
                result,
                "Runtime: {delta} Start: {start} End: {end}".format(
                    **result._result))

    def _print_task_banner(self, task):

        task_name = task.get_name().strip()

        args = ''
        task_args = task.args.copy()
        is_shell = task_args.pop('_uses_shell', False)
        if is_shell and task_name == 'command':
            task_name = 'shell'
        raw_params = task_args.pop('_raw_params', '').split('\n')
        # If there's just a single line, go ahead and print it
        if len(raw_params) == 1 and task_name in ('shell', 'command'):
            task_name = '{name}: {command}'.format(
                name=task_name, command=raw_params[0])

        if not task.no_log and task_args:
            args = u', '.join(u'%s=%s' % a for a in task_args.items())
            args = u' %s' % args

        msg = "TASK [{task}{args}]".format(
            task=task_name,
            args=args)
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

    def _log_message(self, result, msg, status="ok"):
        hostname = self._get_hostname(result)
        self._log("{host} | {status}: {msg}".format(
            host=hostname, status=status, msg=msg))

    def _get_hostname(self, result):
        delegated_vars = result._result.get('_ansible_delegated_vars', None)
        if delegated_vars:
            return "{host} -> {delegated_host}".format(
                host=result._host.get_name(),
                delegated_host=delegated_vars['ansible_host'])
        else:
            return result._host.get_name()
