#!/usr/bin/python

# Copyright (c) 2016 IBM Corp.
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

import glob
import os
import sys
import select
import socket
import subprocess
import threading
import time

LOG_STREAM_FILE = '/tmp/console-{log_uuid}.log'
LOG_STREAM_PORT = 19885


def daemonize():
    # A really basic daemonize method that should work well enough for
    # now in this circumstance. Based on the public domain code at:
    # http://web.archive.org/web/20131017130434/http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/

    pid = os.fork()
    if pid > 0:
        return True

    os.chdir('/')
    os.setsid()
    os.umask(0)

    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()
    i = open('/dev/null', 'r')
    o = open('/dev/null', 'a+')
    e = open('/dev/null', 'a+', 0)
    os.dup2(i.fileno(), sys.stdin.fileno())
    os.dup2(o.fileno(), sys.stdout.fileno())
    os.dup2(e.fileno(), sys.stderr.fileno())
    return False


class Console(object):
    def __init__(self, path):
        self.path = path
        self.file = open(path, 'rb')
        self.stat = os.stat(path)
        self.size = self.stat.st_size


class Server(object):

    MAX_REQUEST_LEN = 1024
    REQUEST_TIMEOUT = 10

    def __init__(self, path, port):
        self.path = path

        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET,
                     socket.SO_REUSEADDR, 1)
        s.bind(('::', port))
        s.listen(1)

        self.socket = s

    def accept(self):
        conn, addr = self.socket.accept()
        return conn

    def run(self):
        while True:
            conn = self.accept()
            t = threading.Thread(target=self.handleOneConnection, args=(conn,))
            t.daemon = True
            t.start()

    def chunkConsole(self, conn, log_uuid):
        try:
            console = Console(self.path.format(log_uuid=log_uuid))
        except Exception:
            return
        while True:
            chunk = console.file.read(4096)
            if not chunk:
                break
            conn.send(chunk)
        return console

    def followConsole(self, console, conn):
        while True:
            # As long as we have unread data, keep reading/sending
            while True:
                chunk = console.file.read(4096)
                if chunk:
                    conn.send(chunk)
                else:
                    break

            # At this point, we are waiting for more data to be written
            time.sleep(0.5)

            # Check to see if the remote end has sent any data, if so,
            # discard
            r, w, e = select.select([conn], [], [conn], 0)
            if conn in e:
                return False
            if conn in r:
                ret = conn.recv(1024)
                # Discard anything read, if input is eof, it has
                # disconnected.
                if not ret:
                    return False

            # See if the file has been truncated
            try:
                st = os.stat(console.path)
                if (st.st_ino != console.stat.st_ino or
                    st.st_size < console.size):
                    return True
            except Exception:
                return True
            console.size = st.st_size

    def get_command(self, conn):
        poll = select.poll()
        bitmask = (select.POLLIN | select.POLLERR |
                   select.POLLHUP | select.POLLNVAL)
        poll.register(conn, bitmask)
        buffer = b''
        ret = None
        start = time.time()
        while True:
            elapsed = time.time() - start
            timeout = max(self.REQUEST_TIMEOUT - elapsed, 0)
            if not timeout:
                raise Exception("Timeout while waiting for input")
            for fd, event in poll.poll(timeout):
                if event & select.POLLIN:
                    buffer += conn.recv(self.MAX_REQUEST_LEN)
                else:
                    raise Exception("Received error event")
            if len(buffer) >= self.MAX_REQUEST_LEN:
                raise Exception("Request too long")
            try:
                ret = buffer.decode('utf-8')
                x = ret.find('\n')
                if x > 0:
                    return ret[:x]
            except UnicodeDecodeError:
                pass

    def handleOneConnection(self, conn):
        log_uuid = self.get_command(conn)
        # use path split to make use the input isn't trying to be clever
        # and construct some path like /tmp/console-/../../something
        log_uuid = os.path.split(log_uuid.rstrip())[-1]

        # FIXME: this won't notice disconnects until it tries to send
        console = None
        try:
            while True:
                if console is not None:
                    try:
                        console.file.close()
                    except Exception:
                        pass
                while True:
                    console = self.chunkConsole(conn, log_uuid)
                    if console:
                        break
                    conn.send('[Zuul] Log not found\n')
                    time.sleep(0.5)
                while True:
                    if self.followConsole(console, conn):
                        break
                    else:
                        return
        finally:
            try:
                conn.close()
            except Exception:
                pass


def get_inode(port_number=19885):
    for netfile in ('/proc/net/tcp6', '/proc/net/tcp'):
        if not os.path.exists(netfile):
            continue
        with open(netfile) as f:
            # discard header line
            f.readline()
            for line in f:
                # sl local_address rem_address st tx_queue:rx_queue tr:tm->when
                # retrnsmt   uid  timeout inode
                fields = line.split()
                # Format is localaddr:localport in hex
                port = int(fields[1].split(':')[1], base=16)
                if port == port_number:
                    return fields[9]


def get_pid_from_inode(inode):
    my_euid = os.geteuid()
    exceptions = []
    for d in os.listdir('/proc'):
        try:
            try:
                int(d)
            except Exception as e:
                continue
            d_abs_path = os.path.join('/proc', d)
            if os.stat(d_abs_path).st_uid != my_euid:
                continue
            fd_dir = os.path.join(d_abs_path, 'fd')
            if os.path.exists(fd_dir):
                if os.stat(fd_dir).st_uid != my_euid:
                    continue
                for fd in os.listdir(fd_dir):
                    try:
                        fd_path = os.path.join(fd_dir, fd)
                        if os.path.islink(fd_path):
                            target = os.readlink(fd_path)
                            if '[' + inode + ']' in target:
                                return d, exceptions
                    except Exception as e:
                        exceptions.append(e)
        except Exception as e:
            exceptions.append(e)
    return None, exceptions


def test():
    s = Server(LOG_STREAM_FILE, LOG_STREAM_PORT)
    s.run()


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(default=LOG_STREAM_FILE),
            port=dict(default=LOG_STREAM_PORT, type='int'),
            state=dict(default='present', choices=['absent', 'present']),
        )
    )

    p = module.params
    path = p['path']
    port = p['port']
    state = p['state']

    if state == 'present':
        if daemonize():
            module.exit_json()

        s = Server(path, port)
        s.run()
    else:
        pid = None
        exceptions = []
        inode = get_inode()
        if not inode:
            module.fail_json(
                "Could not find inode for port",
                exceptions=[])

        pid, exceptions = get_pid_from_inode(inode)
        if not pid:
            except_strings = [str(e) for e in exceptions]
            module.fail_json(
                msg="Could not find zuul_console process for inode",
                exceptions=except_strings)

        try:
            subprocess.check_output(['kill', pid])
        except subprocess.CalledProcessError as e:
            module.fail_json(
                msg="Could not kill zuul_console pid",
                exceptions=[str(e)])

        for fn in glob.glob(LOG_STREAM_FILE.format(log_uuid='*')):
            try:
                os.unlink(fn)
            except Exception as e:
                module.fail_json(
                    msg="Could not remove logfile {fn}".format(fn=fn),
                    exceptions=[str(e)])

        module.exit_json()

from ansible.module_utils.basic import *  # noqa
from ansible.module_utils.basic import AnsibleModule

if __name__ == '__main__':
    main()
# test()
