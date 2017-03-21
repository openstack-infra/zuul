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
    buff = socket.recv(4096)
    buffering = True
    while buffering:
        if "\n" in buff:
            (line, buff) = buff.split("\n", 1)
            yield line + "\n"
        else:
            more = socket.recv(4096)
            if not more:
                buffering = False
            else:
                buff += more
    if buff:
        yield buff


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
