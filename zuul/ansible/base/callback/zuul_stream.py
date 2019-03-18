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
import logging.config
import json
import os
import socket
import threading
import time

from ansible.plugins.callback import default
from zuul.ansible import paths

from zuul.ansible import logconfig

LOG_STREAM_PORT = 19885


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
        self._streamers_stop = False
        self.configure_logger()
        self._items_done = False
        self._deferred_result = None
        self._playbook_name = None

    def configure_logger(self):
        # ansible appends timestamp, user and pid to the log lines emitted
        # to the log file. We're doing other things though, so we don't want
        # this.
        logging_config = logconfig.load_job_config(
            os.environ['ZUUL_JOB_LOG_CONFIG'])

        if self._display.verbosity > 2:
            logging_config.setDebug()

        logging_config.apply()

        self._logger = logging.getLogger('zuul.executor.ansible')

    def _log(self, msg, ts=None, job=True, executor=False, debug=False):
        msg = msg.rstrip()
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
        while True:
            try:
                s = socket.create_connection((ip, LOG_STREAM_PORT), 5)
                # Disable the socket timeout after we have successfully
                # connected to accomodate the fact that jobs may not be writing
                # logs continously. Without this we can easily trip the 5
                # second timeout.
                s.settimeout(None)
            except socket.timeout:
                self._log(
                    "Timeout exception waiting for the logger. "
                    "Please check connectivity to [%s:%s]"
                    % (ip, LOG_STREAM_PORT), executor=True)
                self._log_streamline(
                    "localhost",
                    "Timeout exception waiting for the logger. "
                    "Please check connectivity to [%s:%s]"
                    % (ip, LOG_STREAM_PORT))
                return
            except Exception:
                self._log("[%s] Waiting on logger" % host,
                          executor=True, debug=True)
                time.sleep(0.1)
                continue
            msg = "%s\n" % log_id
            s.send(msg.encode("utf-8"))
            buff = s.recv(4096)
            buffering = True
            while buffering:
                if b'\n' in buff:
                    (line, buff) = buff.split(b'\n', 1)
                    # We can potentially get binary data here. In order to
                    # being able to handle that use the backslashreplace
                    # error handling method. This decodes unknown utf-8
                    # code points to escape sequences which exactly represent
                    # the correct data without throwing a decoding exception.
                    done = self._log_streamline(
                        host, line.decode("utf-8", "backslashreplace"))
                    if done:
                        return
                else:
                    more = s.recv(4096)
                    if not more:
                        buffering = False
                    else:
                        buff += more
            if buff:
                self._log_streamline(
                    host, buff.decode("utf-8", "backslashreplace"))

    def _log_streamline(self, host, line):
        if "[Zuul] Task exit code" in line:
            return True
        elif self._streamers_stop and "[Zuul] Log not found" in line:
            return True
        elif "[Zuul] Log not found" in line:
            # don't output this line
            return False
        else:
            ts, ln = line.split(' | ', 1)

            self._log("%s | %s " % (host, ln), ts=ts)
            return False

    def _log_module_failure(self, result, result_dict):
        if 'module_stdout' in result_dict and result_dict['module_stdout']:
            self._log_message(
                result, status='MODULE FAILURE',
                msg=result_dict['module_stdout'])
        elif 'exception' in result_dict and result_dict['exception']:
            self._log_message(
                result, status='MODULE FAILURE',
                msg=result_dict['exception'])
        elif 'module_stderr' in result_dict:
            self._log_message(
                result, status='MODULE FAILURE',
                msg=result_dict['module_stderr'])

    def v2_playbook_on_start(self, playbook):
        self._playbook_name = os.path.splitext(playbook._file_name)[0]

    def v2_playbook_on_include(self, included_file):
        for host in included_file._hosts:
            self._log("{host} | included: {filename}".format(
                host=host.name,
                filename=included_file._filename))

    def v2_playbook_on_play_start(self, play):
        self._play = play
        # Log an extra blank line to get space before each play
        self._log("")

        # the name of a play defaults to the hosts string
        name = play.get_name().strip()
        msg = u"PLAY [{name}]".format(name=name)

        self._log(msg)

    def v2_playbook_on_task_start(self, task, is_conditional):
        # Log an extra blank line to get space before each task
        self._log("")

        self._task = task

        if self._play.strategy != 'free':
            task_name = self._print_task_banner(task)
        else:
            task_name = task.get_name().strip()

        if task.action in ('command', 'shell'):
            play_vars = self._play._variable_manager._hostvars

            hosts = self._get_task_hosts(task)
            for host, inventory_hostname in hosts:
                if host in ('localhost', '127.0.0.1'):
                    # Don't try to stream from localhost
                    continue
                ip = play_vars[host].get(
                    'ansible_host', play_vars[host].get(
                        'ansible_inventory_host'))
                if ip in ('localhost', '127.0.0.1'):
                    # Don't try to stream from localhost
                    continue
                if task.loop:
                    # Don't try to stream from loops
                    continue
                if play_vars[host].get('ansible_connection') in ('kubectl', ):
                    # Don't try to stream from kubectl connection
                    continue

                log_id = "%s-%s" % (
                    task._uuid, paths._sanitize_filename(inventory_hostname))
                streamer = threading.Thread(
                    target=self._read_log, args=(
                        host, ip, log_id, task_name, hosts))
                streamer.daemon = True
                streamer.start()
                self._streamers.append(streamer)

    def v2_playbook_on_handler_task_start(self, task):
        self.v2_playbook_on_task_start(task, False)

    def _stop_streamers(self):
        self._streamers_stop = True
        while True:
            if not self._streamers:
                break
            streamer = self._streamers.pop()
            streamer.join(30)
            if streamer.is_alive():
                msg = "[Zuul] Log Stream did not terminate"
                self._log(msg, job=True, executor=True)
        self._streamers_stop = False

    def _process_result_for_localhost(self, result, is_task=True):
        result_dict = dict(result._result)
        localhost_names = ('localhost', '127.0.0.1', '::1')
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
            # Normally hosts in the inventory will have ansible_host
            # or ansible_inventory host defined.  The implied
            # inventory record for 'localhost' will have neither, so
            # default to that if none are supplied.
            if task_hostvars.get('ansible_host', task_hostvars.get(
                    'ansible_inventory_host', 'localhost')) in localhost_names:
                is_localhost = True

        if not is_localhost and is_task:
            self._stop_streamers()
        if result._task.action in ('command', 'shell',
                                   'win_command', 'win_shell'):
            stdout_lines = zuul_filter_result(result_dict)
            # We don't have streaming for localhost and windows modules so get
            # standard out after the fact.
            if is_localhost or result._task.action in (
                    'win_command', 'win_shell'):
                for line in stdout_lines:
                    hostname = self._get_hostname(result)
                    self._log("%s | %s " % (hostname, line))

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
        elif result_dict.get('msg', '').startswith('MODULE FAILURE'):
            self._log_module_failure(result, result_dict)
        else:
            self._log_message(
                result=result, status='ERROR', result_dict=result_dict)
        if ignore_errors:
            self._log_message(result, "Ignoring Errors", status="ERROR")

    def v2_runner_on_skipped(self, result):
        if result._task.loop:
            self._items_done = False
            self._deferred_result = dict(result._result)
        else:
            reason = result._result.get('skip_reason')
            if reason:
                # No reason means it's an item, which we'll log differently
                self._log_message(result, status='skipping', msg=reason)

    def v2_runner_item_on_skipped(self, result):
        reason = result._result.get('skip_reason')
        if reason:
            self._log_message(result, status='skipping', msg=reason)
        else:
            self._log_message(result, status='skipping')

        if self._deferred_result:
            self._process_deferred(result)

    def v2_runner_on_ok(self, result):
        if (self._play.strategy == 'free'
                and self._last_task_banner != result._task._uuid):
            self._print_task_banner(result._task)

        result_dict = dict(result._result)

        self._clean_results(result_dict, result._task.action)
        if '_zuul_nolog_return' in result_dict:
            # We have a custom zuul module that doesn't want the parameters
            # from its returned splatted to stdout. This is typically for
            # modules that are collecting data to be displayed some other way.
            for key in list(result_dict.keys()):
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

        elif result_dict.get('msg', '').startswith('MODULE FAILURE'):
            self._log_module_failure(result, result_dict)
        elif result._task.action == 'debug':
            # this is a debug statement, handle it special
            for key in [k for k in result_dict
                        if k.startswith('_ansible')]:
                del result_dict[key]
            if 'changed' in result_dict:
                del result_dict['changed']
            keyname = next(iter(result_dict.keys()))
            # If it has msg, that means it was like:
            #
            #  debug:
            #    msg: Some debug text the user was looking for
            #
            # So we log it with self._log to get just the raw string the
            # user provided. Note that msg may be a multi line block quote
            # so we handle that here as well.
            if keyname == 'msg':
                msg_lines = result_dict['msg'].rstrip().split('\n')
                for msg_line in msg_lines:
                    self._log(msg=msg_line)
            else:
                self._log_message(
                    msg=json.dumps(result_dict, indent=2, sort_keys=True),
                    status=status, result=result)
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
                    "Runtime: {delta}".format(**res))
        elif result_dict.get('msg') == 'All items completed':
            self._log_message(result, result_dict['msg'])
        else:
            self._log_message(
                result,
                "Runtime: {delta}".format(
                    **result_dict))

    def v2_runner_item_on_ok(self, result):
        result_dict = dict(result._result)
        self._process_result_for_localhost(result, is_task=False)

        if result_dict.get('changed', False):
            status = 'changed'
        else:
            status = 'ok'

        if result_dict.get('msg', '').startswith('MODULE FAILURE'):
            self._log_module_failure(result, result_dict)
        elif result._task.action not in ('command', 'shell',
                                         'win_command', 'win_shell'):
            if 'msg' in result_dict:
                self._log_message(
                    result=result, msg=result_dict['msg'], status=status)
            else:
                self._log_message(
                    result=result,
                    msg=json.dumps(result_dict['item'],
                                   indent=2, sort_keys=True),
                    status=status)
        else:
            stdout_lines = zuul_filter_result(result_dict)
            for line in stdout_lines:
                hostname = self._get_hostname(result)
                self._log("%s | %s " % (hostname, line))

            if isinstance(result_dict['item'], str):
                self._log_message(
                    result,
                    "Item: {item} Runtime: {delta}".format(**result_dict))
            else:
                self._log_message(
                    result,
                    "Item: Runtime: {delta}".format(
                        **result_dict))

        if self._deferred_result:
            self._process_deferred(result)

    def v2_runner_item_on_failed(self, result):
        result_dict = dict(result._result)
        self._process_result_for_localhost(result, is_task=False)

        if result_dict.get('msg', '').startswith('MODULE FAILURE'):
            self._log_module_failure(result, result_dict)
        elif result._task.action not in ('command', 'shell',
                                         'win_command', 'win_shell'):
            self._log_message(
                result=result,
                msg="Item: {item}".format(item=result_dict['item']),
                status='ERROR',
                result_dict=result_dict)
        else:
            stdout_lines = zuul_filter_result(result_dict)
            for line in stdout_lines:
                hostname = self._get_hostname(result)
                self._log("%s | %s " % (hostname, line))

            # self._log("Result: %s" % (result_dict))
            self._log_message(
                result, "Item: {item} Result: {rc}".format(**result_dict))

        if self._deferred_result:
            self._process_deferred(result)

    def v2_playbook_on_stats(self, stats):
        # Add a spacer line before the stats so that there will be a line
        # between the last task and the recap
        self._log("")

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
        status = result_dict.get('status')

        if status:
            self._log_message(result, "All items complete", status=status)

        # Log an extra blank line to get space after each task
        self._log("")

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
        result = []

        # _restriction returns the parsed/compiled list of hosts after
        # applying subsets/limits
        hosts = self._play._variable_manager._inventory._restriction
        for inventory_host in hosts:
            # If this task has as delegate to, we don't care about the play
            # hosts, we care about the task's delegate target.
            if task.delegate_to:
                host = task.delegate_to
            else:
                host = inventory_host
            result.append((host, inventory_host))

        return result

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
        if (not msg and result_dict
                and set(result_dict.keys()) == set(['msg', 'failed'])):
            msg = result_dict['msg']
            result_dict = None
        if msg:
            msg_lines = msg.rstrip().split('\n')
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

    v2_runner_on_unreachable = v2_runner_on_failed
