# Copyright (c) 2016 IBM Corp.
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

import logging
import os
import os.path
import re
import select
import threading
import time

from zuul.lib import streamer_utils


class Log(object):

    def __init__(self, path):
        self.path = path
        # The logs are written as binary encoded utf-8, which is what we
        # send over the wire.
        self.file = open(path, 'rb')
        self.stat = os.stat(path)
        self.size = self.stat.st_size


class RequestHandler(streamer_utils.BaseFingerRequestHandler):
    '''
    Class to handle a single log streaming request.

    The log streaming code was blatantly stolen from zuul_console.py. Only
    the (class/method/attribute) names were changed to protect the innocent.
    '''

    log = logging.getLogger("zuul.log_streamer")

    def handle(self):
        try:
            build_uuid = self.getCommand()
        except Exception:
            self.log.exception("Failure during getCommand:")
            msg = 'Internal streaming error'
            self.request.sendall(msg.encode("utf-8"))
            return

        # validate build ID
        if not re.match("[0-9A-Fa-f]+$", build_uuid):
            msg = 'Build ID %s is not valid' % build_uuid
            self.request.sendall(msg.encode("utf-8"))
            return

        job_dir = os.path.join(self.server.jobdir_root, build_uuid)
        if not os.path.exists(job_dir):
            msg = 'Build ID %s not found' % build_uuid
            self.request.sendall(msg.encode("utf-8"))
            return

        # check if log file exists
        log_file = os.path.join(job_dir, 'work', 'logs', 'job-output.txt')
        if not os.path.exists(log_file):
            msg = 'Log not found for build ID %s' % build_uuid
            self.request.sendall(msg.encode("utf-8"))
            return

        try:
            self.stream_log(log_file)
        except Exception:
            self.log.exception("Streaming failure for build UUID %s:",
                               build_uuid)
            msg = 'Internal streaming error'
            self.request.sendall(msg.encode("utf-8"))

    def stream_log(self, log_file):
        log = None
        while True:
            if log is not None:
                try:
                    log.file.close()
                except Exception:
                    pass
            while True:
                log = self.chunk_log(log_file)
                if log:
                    break
                time.sleep(0.5)
            while True:
                if self.follow_log(log):
                    break
                else:
                    if log is not None:
                        try:
                            log.file.close()
                        except Exception:
                            pass
                    return

    def chunk_log(self, log_file):
        try:
            log = Log(log_file)
        except Exception:
            return
        while True:
            chunk = log.file.read(4096)
            if not chunk:
                break
            self.request.send(chunk)
        return log

    def follow_log(self, log):
        while True:
            # As long as we have unread data, keep reading/sending
            while True:
                chunk = log.file.read(4096)
                if chunk:
                    self.request.send(chunk)
                else:
                    break

            # See if the file has been removed, meaning we should stop
            # streaming it.
            if not os.path.exists(log.path):
                return False

            # At this point, we are waiting for more data to be written
            time.sleep(0.5)

            # Check to see if the remote end has sent any data, if so,
            # discard
            r, w, e = select.select([self.request], [], [self.request], 0)
            if self.request in e:
                return False
            if self.request in r:
                ret = self.request.recv(1024)
                # Discard anything read, if input is eof, it has
                # disconnected.
                if not ret:
                    return False


class LogStreamerServer(streamer_utils.CustomThreadingTCPServer):

    def __init__(self, *args, **kwargs):
        self.jobdir_root = kwargs.pop('jobdir_root')
        super(LogStreamerServer, self).__init__(*args, **kwargs)


class LogStreamer(object):
    '''
    Class implementing log streaming over the finger daemon port.
    '''

    def __init__(self, host, port, jobdir_root):
        self.log = logging.getLogger('zuul.log_streamer')
        self.log.debug("LogStreamer starting on port %s", port)
        self.server = LogStreamerServer((host, port),
                                        RequestHandler,
                                        jobdir_root=jobdir_root)

        # We start the actual serving within a thread so we can return to
        # the owner.
        self.thd = threading.Thread(target=self._run)
        self.thd.daemon = True
        self.thd.start()

    def _run(self):
        try:
            self.server.serve_forever()
        except Exception:
            self.log.exception("Abnormal termination:")
            raise

    def stop(self):
        if self.thd.isAlive():
            self.server.shutdown()
            self.server.server_close()
            self.thd.join()
            self.log.debug("LogStreamer stopped")
