#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2016 Red Hat, Inc.
# Copyright (c) 2016 IBM Corp.
# (c) 2012, Michael DeHaan <michael.dehaan@gmail.com>, and others
# (c) 2016, Toshio Kuratomi <tkuratomi@ansible.com>
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['stableinterface'],
                    'supported_by': 'core'}

# flake8: noqa
# This file shares a significant chunk of code with an upstream ansible
# function, run_command. The goal is to not have to fork quite so much
# of that function, and discussing that design with upstream means we
# should keep the changes to substantive ones only. For that reason, this
# file is purposely not enforcing pep8, as making the function pep8 clean
# would remove our ability to easily have a discussion with our friends
# upstream

DOCUMENTATION = '''
---
module: command
short_description: Executes a command on a remote node
version_added: historical
description:
     - The C(command) module takes the command name followed by a list of space-delimited arguments.
     - The given command will be executed on all selected nodes. It will not be
       processed through the shell, so variables like C($HOME) and operations
       like C("<"), C(">"), C("|"), C(";") and C("&") will not work (use the M(shell)
       module if you need these features).
options:
  free_form:
    description:
      - the command module takes a free form command to run.  There is no parameter actually named 'free form'.
        See the examples!
    required: true
    default: null
  creates:
    description:
      - a filename or (since 2.0) glob pattern, when it already exists, this step will B(not) be run.
    required: no
    default: null
  removes:
    description:
      - a filename or (since 2.0) glob pattern, when it does not exist, this step will B(not) be run.
    version_added: "0.8"
    required: no
    default: null
  chdir:
    description:
      - cd into this directory before running the command
    version_added: "0.6"
    required: false
    default: null
  executable:
    description:
      - change the shell used to execute the command. Should be an absolute path to the executable.
    required: false
    default: null
    version_added: "0.9"
  warn:
    version_added: "1.8"
    default: yes
    description:
      - if command warnings are on in ansible.cfg, do not warn about this particular line if set to no/false.
    required: false
notes:
    -  If you want to run a command through the shell (say you are using C(<), C(>), C(|), etc), you actually want the M(shell) module instead.
       The C(command) module is much more secure as it's not affected by the user's environment.
    -  " C(creates), C(removes), and C(chdir) can be specified after the command.
       For instance, if you only want to run a command if a certain file does not exist, use this."
author:
    - Ansible Core Team
    - Michael DeHaan
'''

EXAMPLES = '''
- name: return motd to registered var
  command: cat /etc/motd
  register: mymotd

- name: Run the command if the specified file does not exist.
  command: /usr/bin/make_database.sh arg1 arg2 creates=/path/to/database

# You can also use the 'args' form to provide the options.
- name: This command will change the working directory to somedir/ and will only run when /path/to/database doesn't exist.
  command: /usr/bin/make_database.sh arg1 arg2
  args:
    chdir: somedir/
    creates: /path/to/database

- name: safely use templated variable to run command. Always use the quote filter to avoid injection issues.
  command: cat {{ myfile|quote }}
  register: myoutput
'''

import datetime
import glob
import pipes
import re
import shlex
import os

import getpass
import select
import subprocess
import traceback
import threading

from ansible.module_utils.basic import AnsibleModule, heuristic_log_sanitize
from ansible.module_utils.pycompat24 import get_exception, literal_eval
from ansible.module_utils.six import (
    PY2,
    PY3,
    b,
    binary_type,
    integer_types,
    iteritems,
    string_types,
    text_type,
)
from ansible.module_utils.six.moves import map, reduce
from ansible.module_utils._text import to_native, to_bytes, to_text

LOG_STREAM_FILE = '/tmp/console-{log_uuid}.log'
PASSWD_ARG_RE = re.compile(r'^[-]{0,2}pass[-]?(word|wd)?')
# List to save stdout log lines in as we collect them
_log_lines = []


class Console(object):
    def __init__(self, log_uuid):
        self.logfile_name = LOG_STREAM_FILE.format(log_uuid=log_uuid)

    def __enter__(self):
        self.logfile = open(self.logfile_name, 'ab', buffering=0)
        return self

    def __exit__(self, etype, value, tb):
        self.logfile.close()

    def addLine(self, ln):
        # Note this format with deliminator is "inspired" by the old
        # Jenkins format but with microsecond resolution instead of
        # millisecond.  It is kept so log parsing/formatting remains
        # consistent.
        ts = str(datetime.datetime.now()).encode('utf-8')
        if not isinstance(ln, bytes):
            try:
                ln = ln.encode('utf-8')
            except Exception:
                ln = repr(ln).encode('utf-8') + b'\n'
        outln = b'%s | %s' % (ts, ln)
        self.logfile.write(outln)


def follow(fd, log_uuid):
    newline_warning = False
    with Console(log_uuid) as console:
        while True:
            line = fd.readline()
            if not line:
                break
            _log_lines.append(line)
            if not line.endswith(b'\n'):
                line += b'\n'
                newline_warning = True
            console.addLine(line)
        if newline_warning:
            console.addLine('[Zuul] No trailing newline\n')


# Taken from ansible/module_utils/basic.py ... forking the method for now
# so that we can dive in and figure out how to make appropriate hook points
def zuul_run_command(self, args, zuul_log_id, check_rc=False, close_fds=True, executable=None, data=None, binary_data=False, path_prefix=None, cwd=None, use_unsafe_shell=False, prompt_regex=None, environ_update=None, umask=None, encoding='utf-8', errors='surrogate_or_strict'):
    '''
    Execute a command, returns rc, stdout, and stderr.

    :arg args: is the command to run
        * If args is a list, the command will be run with shell=False.
        * If args is a string and use_unsafe_shell=False it will split args to a list and run with shell=False
        * If args is a string and use_unsafe_shell=True it runs with shell=True.
    :kw check_rc: Whether to call fail_json in case of non zero RC.
        Default False
    :kw close_fds: See documentation for subprocess.Popen(). Default True
    :kw executable: See documentation for subprocess.Popen(). Default None
    :kw data: If given, information to write to the stdin of the command
    :kw binary_data: If False, append a newline to the data.  Default False
    :kw path_prefix: If given, additional path to find the command in.
        This adds to the PATH environment vairable so helper commands in
        the same directory can also be found
    :kw cwd: If given, working directory to run the command inside
    :kw use_unsafe_shell: See `args` parameter.  Default False
    :kw prompt_regex: Regex string (not a compiled regex) which can be
        used to detect prompts in the stdout which would otherwise cause
        the execution to hang (especially if no input data is specified)
    :kw environ_update: dictionary to *update* os.environ with
    :kw umask: Umask to be used when running the command. Default None
    :kw encoding: Since we return native strings, on python3 we need to
        know the encoding to use to transform from bytes to text.  If you
        want to always get bytes back, use encoding=None.  The default is
        "utf-8".  This does not affect transformation of strings given as
        args.
    :kw errors: Since we return native strings, on python3 we need to
        transform stdout and stderr from bytes to text.  If the bytes are
        undecodable in the ``encoding`` specified, then use this error
        handler to deal with them.  The default is ``surrogate_or_strict``
        which means that the bytes will be decoded using the
        surrogateescape error handler if available (available on all
        python3 versions we support) otherwise a UnicodeError traceback
        will be raised.  This does not affect transformations of strings
        given as args.
    :returns: A 3-tuple of return code (integer), stdout (native string),
        and stderr (native string).  On python2, stdout and stderr are both
        byte strings.  On python3, stdout and stderr are text strings converted
        according to the encoding and errors parameters.  If you want byte
        strings on python3, use encoding=None to turn decoding to text off.
    '''

    shell = False
    if isinstance(args, list):
        if use_unsafe_shell:
            args = " ".join([pipes.quote(x) for x in args])
            shell = True
    elif isinstance(args, (binary_type, text_type)) and use_unsafe_shell:
        shell = True
    elif isinstance(args, (binary_type, text_type)):
        # On python2.6 and below, shlex has problems with text type
        # On python3, shlex needs a text type.
        if PY2:
            args = to_bytes(args, errors='surrogate_or_strict')
        elif PY3:
            args = to_text(args, errors='surrogateescape')
        args = shlex.split(args)
    else:
        msg = "Argument 'args' to run_command must be list or string"
        self.fail_json(rc=257, cmd=args, msg=msg)

    prompt_re = None
    if prompt_regex:
        if isinstance(prompt_regex, text_type):
            if PY3:
                prompt_regex = to_bytes(prompt_regex, errors='surrogateescape')
            elif PY2:
                prompt_regex = to_bytes(prompt_regex, errors='surrogate_or_strict')
        try:
            prompt_re = re.compile(prompt_regex, re.MULTILINE)
        except re.error:
            self.fail_json(msg="invalid prompt regular expression given to run_command")

    # expand things like $HOME and ~
    if not shell:
        args = [os.path.expanduser(os.path.expandvars(x)) for x in args if x is not None]

    rc = 0
    msg = None
    st_in = None

    # Manipulate the environ we'll send to the new process
    old_env_vals = {}
    # We can set this from both an attribute and per call
    for key, val in self.run_command_environ_update.items():
        old_env_vals[key] = os.environ.get(key, None)
        os.environ[key] = val
    if environ_update:
        for key, val in environ_update.items():
            old_env_vals[key] = os.environ.get(key, None)
            os.environ[key] = val
    if path_prefix:
        old_env_vals['PATH'] = os.environ['PATH']
        os.environ['PATH'] = "%s:%s" % (path_prefix, os.environ['PATH'])

    # If using test-module and explode, the remote lib path will resemble ...
    #   /tmp/test_module_scratch/debug_dir/ansible/module_utils/basic.py
    # If using ansible or ansible-playbook with a remote system ...
    #   /tmp/ansible_vmweLQ/ansible_modlib.zip/ansible/module_utils/basic.py

    # Clean out python paths set by ansiballz
    if 'PYTHONPATH' in os.environ:
        pypaths = os.environ['PYTHONPATH'].split(':')
        pypaths = [x for x in pypaths
                   if not x.endswith('/ansible_modlib.zip') and
                   not x.endswith('/debug_dir')]
        os.environ['PYTHONPATH'] = ':'.join(pypaths)
        if not os.environ['PYTHONPATH']:
            del os.environ['PYTHONPATH']

    # create a printable version of the command for use
    # in reporting later, which strips out things like
    # passwords from the args list
    to_clean_args = args
    if PY2:
        if isinstance(args, text_type):
            to_clean_args = to_bytes(args)
    else:
        if isinstance(args, binary_type):
            to_clean_args = to_text(args)
    if isinstance(args, (text_type, binary_type)):
        to_clean_args = shlex.split(to_clean_args)

    clean_args = []
    is_passwd = False
    for arg in to_clean_args:
        if is_passwd:
            is_passwd = False
            clean_args.append('********')
            continue
        if PASSWD_ARG_RE.match(arg):
            sep_idx = arg.find('=')
            if sep_idx > -1:
                clean_args.append('%s=********' % arg[:sep_idx])
                continue
            else:
                is_passwd = True
        arg = heuristic_log_sanitize(arg, self.no_log_values)
        clean_args.append(arg)
    clean_args = ' '.join(pipes.quote(arg) for arg in clean_args)

    if data:
        st_in = subprocess.PIPE

    # ZUUL: changed stderr to follow stdout
    kwargs = dict(
        executable=executable,
        shell=shell,
        close_fds=close_fds,
        stdin=st_in,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # store the pwd
    prev_dir = os.getcwd()

    # make sure we're in the right working directory
    if cwd and os.path.isdir(cwd):
        cwd = os.path.abspath(os.path.expanduser(cwd))
        kwargs['cwd'] = cwd
        try:
            os.chdir(cwd)
        except (OSError, IOError):
            e = get_exception()
            self.fail_json(rc=e.errno, msg="Could not open %s, %s" % (cwd, str(e)))

    old_umask = None
    if umask:
        old_umask = os.umask(umask)

    t = None
    fail_json_kwargs = None
    ret = None

    try:
        if self._debug:
            self.log('Executing: ' + clean_args)

        # ZUUL: Replaced the excution loop with the zuul_runner run function
        cmd = subprocess.Popen(args, **kwargs)
        t = threading.Thread(target=follow, args=(cmd.stdout, zuul_log_id))
        t.daemon = True
        t.start()

        ret = cmd.wait()

        # Give the thread that is writing the console log up to 10 seconds
        # to catch up and exit.  If it hasn't done so by then, it is very
        # likely stuck in readline() because it spawed a child that is
        # holding stdout or stderr open.
        t.join(10)
        with Console(zuul_log_id) as console:
            if t.isAlive():
                console.addLine("[Zuul] standard output/error still open "
                                "after child exited")
            console.addLine("[Zuul] Task exit code: %s\n" % ret)

        # ZUUL: If the console log follow thread *is* stuck in readline,
        # we can't close stdout (attempting to do so raises an
        # exception) , so this is disabled.
        # cmd.stdout.close()
        # cmd.stderr.close()

        # ZUUL: stdout and stderr are in the console log file
        # ZUUL: return the saved log lines so we can ship them back
        stdout = b('').join(_log_lines)
        stderr = b('')

        rc = cmd.returncode
    except (OSError, IOError):
        e = get_exception()
        self.log("Error Executing CMD:%s Exception:%s" % (clean_args, to_native(e)))
        fail_json_kwargs=dict(rc=e.errno, msg=str(e), cmd=clean_args)
    except Exception:
        e = get_exception()
        self.log("Error Executing CMD:%s Exception:%s" % (clean_args, to_native(traceback.format_exc())))
        fail_json_kwargs = dict(rc=257, msg=str(e), exception=traceback.format_exc(), cmd=clean_args)
    finally:
        if t:
            with Console(zuul_log_id) as console:
                if t.isAlive():
                    console.addLine("[Zuul] standard output/error still open "
                                    "after child exited")
                if ret is None and fail_json_kwargs:
                    ret = fail_json_kwargs['rc']
                elif ret is None and not fail_json_kwargs:
                    ret = -1
                console.addLine("[Zuul] Task exit code: %s\n" % ret)
                if ret == -1 and not fail_json_kwargs:
                    self.fail_json(rc=ret, msg="Something went horribly wrong during task execution")

        if fail_json_kwargs:
            self.fail_json(**fail_json_kwargs)

    # Restore env settings
    for key, val in old_env_vals.items():
        if val is None:
            del os.environ[key]
        else:
            os.environ[key] = val

    if old_umask:
        os.umask(old_umask)

    if rc != 0 and check_rc:
        msg = heuristic_log_sanitize(stderr.rstrip(), self.no_log_values)
        self.fail_json(cmd=clean_args, rc=rc, stdout=stdout, stderr=stderr, msg=msg)

    # reset the pwd
    os.chdir(prev_dir)

    if encoding is not None:
        return (rc, to_native(stdout, encoding=encoding, errors=errors),
                to_native(stderr, encoding=encoding, errors=errors))
    return (rc, stdout, stderr)


def check_command(commandline):
    arguments = { 'chown': 'owner', 'chmod': 'mode', 'chgrp': 'group',
                  'ln': 'state=link', 'mkdir': 'state=directory',
                  'rmdir': 'state=absent', 'rm': 'state=absent', 'touch': 'state=touch' }
    commands  = { 'hg': 'hg', 'curl': 'get_url or uri', 'wget': 'get_url or uri',
                  'svn': 'subversion', 'service': 'service',
                  'mount': 'mount', 'rpm': 'yum, dnf or zypper', 'yum': 'yum', 'apt-get': 'apt',
                  'tar': 'unarchive', 'unzip': 'unarchive', 'sed': 'template or lineinfile',
                  'dnf': 'dnf', 'zypper': 'zypper' }
    become   = [ 'sudo', 'su', 'pbrun', 'pfexec', 'runas' ]
    warnings = list()
    command = os.path.basename(commandline.split()[0])
    if command in arguments:
        warnings.append("Consider using file module with %s rather than running %s" % (arguments[command], command))
    if command in commands:
        warnings.append("Consider using %s module rather than running %s" % (commands[command], command))
    if command in become:
        warnings.append("Consider using 'become', 'become_method', and 'become_user' rather than running %s" % (command,))
    return warnings


def main():

    # the command module is the one ansible module that does not take key=value args
    # hence don't copy this one if you are looking to build others!
    module = AnsibleModule(
        argument_spec=dict(
            _raw_params = dict(),
            _uses_shell = dict(type='bool', default=False),
            chdir = dict(type='path'),
            executable = dict(),
            creates = dict(type='path'),
            removes = dict(type='path'),
            warn = dict(type='bool', default=True),
            environ = dict(type='dict', default=None),
            zuul_log_id = dict(type='str'),
        )
    )

    shell = module.params['_uses_shell']
    chdir = module.params['chdir']
    executable = module.params['executable']
    args = module.params['_raw_params']
    creates = module.params['creates']
    removes = module.params['removes']
    warn = module.params['warn']
    environ = module.params['environ']
    zuul_log_id = module.params['zuul_log_id']

    if args.strip() == '':
        module.fail_json(rc=256, msg="no command given")

    if chdir:
        chdir = os.path.abspath(chdir)
        os.chdir(chdir)

    if creates:
        # do not run the command if the line contains creates=filename
        # and the filename already exists.  This allows idempotence
        # of command executions.
        if glob.glob(creates):
            module.exit_json(
                cmd=args,
                stdout="skipped, since %s exists" % creates,
                changed=False,
                rc=0
            )

    if removes:
        # do not run the command if the line contains removes=filename
        # and the filename does not exist.  This allows idempotence
        # of command executions.
        if not glob.glob(removes):
            module.exit_json(
                cmd=args,
                stdout="skipped, since %s does not exist" % removes,
                changed=False,
                rc=0
            )

    warnings = list()
    if warn:
        warnings = check_command(args)

    if not shell:
        args = shlex.split(args)
    startd = datetime.datetime.now()

    rc, out, err = zuul_run_command(module, args, zuul_log_id, executable=executable, use_unsafe_shell=shell, encoding=None, environ_update=environ)

    endd = datetime.datetime.now()
    delta = endd - startd

    if out is None:
        out = b('')
    if err is None:
        err = b('')

    module.exit_json(
        cmd      = args,
        stdout   = out.rstrip(b("\r\n")),
        stderr   = err.rstrip(b("\r\n")),
        rc       = rc,
        start    = str(startd),
        end      = str(endd),
        delta    = str(delta),
        changed  = True,
        warnings = warnings,
        zuul_log_id = zuul_log_id
    )

if __name__ == '__main__':
    main()
