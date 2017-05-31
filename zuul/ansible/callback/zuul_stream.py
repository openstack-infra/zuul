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

import os
import multiprocessing
import socket
import time

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

    for key in ('changed', 'cmd',
                'stderr', 'stderr_lines',
                'stdout', 'stdout_lines'):
        result.pop(key, None)
    return result


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
        self._daemon_stamp = 'daemon-stamp-%s'
        self._host_dict = {}

    def _read_log(self, host, ip):
        self._display.display("[%s] starting to log" % host)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                s.connect((ip, LOG_STREAM_PORT))
            except Exception:
                self._display.display("[%s] Waiting on logger" % host)
                time.sleep(0.1)
                continue
            for line in linesplit(s):
                self._display.display("[%s] %s " % (host, line.strip()))

    def v2_playbook_on_play_start(self, play):
        self._play = play
        super(CallbackModule, self).v2_playbook_on_play_start(play)

    def v2_playbook_on_task_start(self, task, is_conditional):
        self._task = task

        if self._play.strategy != 'free':
            self._print_task_banner(task)
        if task.action == 'command':
            play_vars = self._play._variable_manager._hostvars

            hosts = self._play.hosts
            if 'all' in hosts:
                # NOTE(jamielennox): play.hosts is purely the list of hosts
                # that was provided not interpretted by inventory. We don't
                # have inventory access here but we can assume that 'all' is
                # everything in hostvars.
                hosts = play_vars.keys()

            for host in hosts:
                ip = play_vars[host]['ansible_host']
                daemon_stamp = self._daemon_stamp % host
                if not os.path.exists(daemon_stamp):
                    self._host_dict[host] = ip
                    # Touch stamp file
                    open(daemon_stamp, 'w').close()
                    p = multiprocessing.Process(
                        target=self._read_log, args=(host, ip))
                    p.daemon = True
                    p.start()

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if result._task.action in ('command', 'shell'):
            zuul_filter_result(result._result)
        super(CallbackModule, self).v2_runner_on_failed(
            result, ignore_errors=ignore_errors)

    def v2_runner_on_ok(self, result):
        if result._task.action in ('command', 'shell'):
            zuul_filter_result(result._result)
        else:
            return super(CallbackModule, self).v2_runner_on_ok(result)

        if self._play.strategy == 'free':
            return super(CallbackModule, self).v2_runner_on_ok(result)

        delegated_vars = result._result.get('_ansible_delegated_vars', None)

        if delegated_vars:
            msg = "ok: [{host} -> {delegated_host} %s]".format(
                host=result._host.get_name(),
                delegated_host=delegated_vars['ansible_host'])
        else:
            msg = "ok: [{host}]".format(host=result._host.get_name())

        if result._task.loop and 'results' in result._result:
            self._process_items(result)
        else:
            msg += " Runtime: {delta} Start: {start} End: {end}".format(
                **result._result)

        self._handle_warnings(result._result)

        self._display.display(msg)
