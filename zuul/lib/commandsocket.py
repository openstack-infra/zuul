# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
# Copyright 2016 Red Hat
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

import logging
import os
import socket
import threading
import queue


class CommandSocket(object):
    log = logging.getLogger("zuul.CommandSocket")

    def __init__(self, path):
        self.running = False
        self.path = path
        self.queue = queue.Queue()

    def start(self):
        self.running = True
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.path)
        self.socket.listen(1)
        self.socket_thread = threading.Thread(target=self._socketListener)
        self.socket_thread.daemon = True
        self.socket_thread.start()

    def stop(self):
        # First, wake up our listener thread with a connection and
        # tell it to stop running.
        self.running = False
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.path)
            s.sendall(b'_stop\n')
        # The command '_stop' will be ignored by our listener, so
        # directly inject it into the queue so that consumers of this
        # class which are waiting in .get() are awakened.  They can
        # either handle '_stop' or just ignore the unknown command and
        # then check to see if they should continue to run before
        # re-entering their loop.
        self.queue.put(b'_stop')
        self.socket_thread.join()
        self.socket.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _socketListener(self):
        while self.running:
            try:
                s, addr = self.socket.accept()
                self.log.debug("Accepted socket connection %s" % (s,))
                buf = b''
                while True:
                    buf += s.recv(1)
                    if buf[-1:] == b'\n':
                        break
                buf = buf.strip()
                self.log.debug("Received %s from socket" % (buf,))
                s.close()
                # Because we use '_stop' internally to wake up a
                # waiting thread, don't allow it to actually be
                # injected externally.
                if buf != b'_stop':
                    self.queue.put(buf)
            except Exception:
                self.log.exception("Exception in socket handler")

    def get(self):
        if not self.running:
            raise Exception("CommandSocket.get called while stopped")
        return self.queue.get()
