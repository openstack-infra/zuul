#!/usr/bin/env python
# Copyright 2017 Red Hat, Inc.
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

'''
This file contains code common to finger log streaming functionality.
The log streamer process within each executor, the finger gateway service,
and the web interface will all make use of this module.
'''

import os
import pwd
import select
import socket
import socketserver
import threading
import time


class BaseFingerRequestHandler(socketserver.BaseRequestHandler):
    '''
    Base class for common methods for handling finger requests.
    '''

    MAX_REQUEST_LEN = 1024
    REQUEST_TIMEOUT = 10

    def getCommand(self):
        poll = select.poll()
        bitmask = (select.POLLIN | select.POLLERR |
                   select.POLLHUP | select.POLLNVAL)
        poll.register(self.request, bitmask)
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
                    buffer += self.request.recv(self.MAX_REQUEST_LEN)
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


class CustomThreadingTCPServer(socketserver.ThreadingTCPServer):
    '''
    Custom version that allows us to drop privileges after port binding.
    '''

    address_family = socket.AF_INET6

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        self.pid_file = kwargs.pop('pid_file', None)
        socketserver.ThreadingTCPServer.__init__(self, *args, **kwargs)

    def change_privs(self):
        '''
        Drop our privileges to another user.
        '''
        if os.getuid() != 0:
            return

        pw = pwd.getpwnam(self.user)

        # Change owner on our pid file so it can be removed by us after
        # dropping privileges. May not exist if not a daemon.
        if self.pid_file and os.path.exists(self.pid_file):
            os.chown(self.pid_file, pw.pw_uid, pw.pw_gid)

        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.umask(0o022)

    def server_bind(self):
        '''
        Overridden from the base class to allow address reuse and to drop
        privileges after binding to the listening socket.
        '''
        self.allow_reuse_address = True
        socketserver.ThreadingTCPServer.server_bind(self)
        if self.user:
            self.change_privs()

    def server_close(self):
        '''
        Overridden from base class to shutdown the socket immediately.
        '''
        try:
            self.socket.shutdown(socket.SHUT_RD)
            self.socket.close()
        except socket.error as e:
            # If it's already closed, don't error.
            if e.errno == socket.EBADF:
                return
            raise

    def process_request(self, request, client_address):
        '''
        Overridden from the base class to name the thread.
        '''
        t = threading.Thread(target=self.process_request_thread,
                             name='socketserver_Thread',
                             args=(request, client_address))
        t.daemon = self.daemon_threads
        t.start()
