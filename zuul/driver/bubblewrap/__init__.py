# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
# Copyright 2016 Red Hat, Inc.
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

import argparse
import fcntl
import grp
import logging
import os
import psutil
import pwd
import shlex
import subprocess
import sys
import threading
import re
import struct

from typing import Dict, List  # flake8: noqa

from zuul.driver import (Driver, WrapperInterface)
from zuul.execution_context import BaseExecutionContext


class WrappedPopen(object):
    def __init__(self, command, fds):
        self.command = command
        self.fds = fds

    def __call__(self, args, *sub_args, **kwargs):
        try:
            args = self.command + args
            if kwargs.get('close_fds') or sys.version_info.major >= 3:
                # The default in py3 is close_fds=True, so we need to pass
                # our open fds in. However, this can only work right in
                # py3.2 or later due to the lack of 'pass_fds' in prior
                # versions. So until we are py3 only we can only bwrap
                # things that are close_fds=False
                pass_fds = list(kwargs.get('pass_fds', []))
                for fd in self.fds:
                    if fd not in pass_fds:
                        pass_fds.append(fd)
                kwargs['pass_fds'] = pass_fds
            proc = psutil.Popen(args, *sub_args, **kwargs)
        finally:
            self.__del__()
        return proc

    def __del__(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []


class BubblewrapExecutionContext(BaseExecutionContext):
    log = logging.getLogger("zuul.BubblewrapExecutionContext")

    def __init__(self, bwrap_command, ro_paths, rw_paths, secrets):
        self.bwrap_command = bwrap_command
        self.mounts_map = {'ro': ro_paths, 'rw': rw_paths}
        self.secrets = secrets

    def startPipeWriter(self, pipe, data):
        # In case we have a large amount of data to write through a
        # pipe, spawn a thread to handle the writes.
        t = threading.Thread(target=self._writer, args=(pipe, data))
        t.daemon = True
        t.start()

    def _writer(self, pipe, data):
        os.write(pipe, data)
        os.close(pipe)

    def setpag(self):
        # If we are on a system with AFS, ensure that each playbook
        # invocation ends up in its own PAG.
        # http://asa.scripts.mit.edu/trac/attachment/ticket/145/setpag.txt#L315
        if os.path.exists("/proc/fs/openafs/afs_ioctl"):
            fcntl.ioctl(open("/proc/fs/openafs/afs_ioctl"), 0x40084301,
                        struct.pack("lllll", 0, 0, 0, 0, 21))

    def getPopen(self, **kwargs):
        self.setpag()
        # Set zuul_dir if it was not passed in
        if 'zuul_dir' in kwargs:
            zuul_dir = kwargs['zuul_dir']
        else:
            zuul_python_dir = os.path.dirname(sys.executable)
            # We want the dir directly above bin to get the whole venv
            zuul_dir = os.path.normpath(os.path.join(zuul_python_dir, '..'))

        bwrap_command = list(self.bwrap_command)
        if not zuul_dir.startswith('/usr'):
            bwrap_command.extend(['--ro-bind', zuul_dir, zuul_dir])

        for mount_type in ('ro', 'rw'):
            bind_arg = '--ro-bind' if mount_type == 'ro' else '--bind'
            for bind in self.mounts_map[mount_type]:
                bwrap_command.extend([bind_arg, bind, bind])

        # A list of file descriptors which must be held open so that
        # bwrap may read from them.
        read_fds = []
        # Need users and groups
        uid = os.getuid()
        passwd = list(pwd.getpwuid(uid))
        # Replace our user's actual home directory with the work dir.
        passwd = passwd[:5] + [kwargs['work_dir']] + passwd[6:]
        passwd_bytes = b':'.join(
            ['{}'.format(x).encode('utf8') for x in passwd])
        (passwd_r, passwd_w) = os.pipe()
        os.write(passwd_w, passwd_bytes)
        os.write(passwd_w, b'\n')
        os.close(passwd_w)
        read_fds.append(passwd_r)

        gid = os.getgid()
        group = grp.getgrgid(gid)
        group_bytes = b':'.join(
            ['{}'.format(x).encode('utf8') for x in group])
        group_r, group_w = os.pipe()
        os.write(group_w, group_bytes)
        os.write(group_w, b'\n')
        os.close(group_w)
        read_fds.append(group_r)

        # Create a tmpfs for each directory which holds secrets, and
        # tell bubblewrap to write the contents to a file therein.
        secret_dirs = set()
        for fn, content in self.secrets.items():
            secret_dir = os.path.dirname(fn)
            if secret_dir not in secret_dirs:
                bwrap_command.extend(['--tmpfs', secret_dir])
                secret_dirs.add(secret_dir)
            secret_r, secret_w = os.pipe()
            self.startPipeWriter(secret_w, content.encode('utf8'))
            bwrap_command.extend(['--file', str(secret_r), fn])
            read_fds.append(secret_r)

        kwargs = dict(kwargs)  # Don't update passed in dict
        kwargs['uid'] = uid
        kwargs['gid'] = gid
        kwargs['uid_fd'] = passwd_r
        kwargs['gid_fd'] = group_r
        command = [x.format(**kwargs) for x in bwrap_command]

        self.log.debug("Bubblewrap command: %s",
                       " ".join(shlex.quote(c) for c in command))

        wrapped_popen = WrappedPopen(command, read_fds)

        return wrapped_popen


class BubblewrapDriver(Driver, WrapperInterface):
    log = logging.getLogger("zuul.BubblewrapDriver")
    name = 'bubblewrap'

    release_file_re = re.compile('^\W+-release$')

    def __init__(self):
        self.bwrap_command = self._bwrap_command()

    def reconfigure(self, tenant):
        pass

    def stop(self):
        pass

    def _bwrap_command(self):
        bwrap_command = [
            'bwrap',
            '--dir', '/tmp',
            '--tmpfs', '/tmp',
            '--dir', '/var',
            '--dir', '/var/tmp',
            '--dir', '/run/user/{uid}',
            '--ro-bind', '/usr', '/usr',
            '--ro-bind', '/lib', '/lib',
            '--ro-bind', '/bin', '/bin',
            '--ro-bind', '/sbin', '/sbin',
            '--ro-bind', '/etc/resolv.conf', '/etc/resolv.conf',
            '--ro-bind', '/etc/hosts', '/etc/hosts',
            '--ro-bind', '/etc/localtime', '/etc/localtime',
            '--ro-bind', '{ssh_auth_sock}', '{ssh_auth_sock}',
            '--bind', '{work_dir}', '{work_dir}',
            '--proc', '/proc',
            '--dev', '/dev',
            '--chdir', '{work_dir}',
            '--unshare-all',
            '--share-net',
            '--die-with-parent',
            '--uid', '{uid}',
            '--gid', '{gid}',
            '--file', '{uid_fd}', '/etc/passwd',
            '--file', '{gid_fd}', '/etc/group',
        ]

        for path in ['/lib64',
                     '/etc/nsswitch.conf',
                     '/etc/lsb-release.d',
                     '/etc/alternatives',
                     '/etc/ssl/certs',
                     ]:
            if os.path.exists(path):
                bwrap_command.extend(['--ro-bind', path, path])
        for fn in os.listdir('/etc'):
            if self.release_file_re.match(fn):
                path = os.path.join('/etc', fn)
                bwrap_command.extend(['--ro-bind', path, path])

        return bwrap_command

    def getExecutionContext(self, ro_paths=None, rw_paths=None, secrets=None):
        if not ro_paths:
            ro_paths = []
        if not rw_paths:
            rw_paths = []
        if not secrets:
            secrets = {}
        return BubblewrapExecutionContext(
            self.bwrap_command,
            ro_paths, rw_paths,
            secrets)


def main(args=None):
    logging.basicConfig(level=logging.DEBUG)

    driver = BubblewrapDriver()

    parser = argparse.ArgumentParser()
    parser.add_argument('--ro-paths', nargs='+')
    parser.add_argument('--rw-paths', nargs='+')
    parser.add_argument('--secret', nargs='+')
    parser.add_argument('work_dir')
    parser.add_argument('run_args', nargs='+')
    cli_args = parser.parse_args()

    ssh_auth_sock = os.environ.get('SSH_AUTH_SOCK')

    secrets = {}
    if cli_args.secret:
        for secret in cli_args.secret:
            fn, content = secret.split('=', 1)
            secrets[fn]=content

    context = driver.getExecutionContext(
        cli_args.ro_paths, cli_args.rw_paths,
        secrets)

    popen = context.getPopen(work_dir=cli_args.work_dir,
                             ssh_auth_sock=ssh_auth_sock)
    x = popen(cli_args.run_args)
    x.wait()


if __name__ == '__main__':
    main()
