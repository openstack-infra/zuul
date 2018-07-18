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

import functools
import logging
import socket
import threading

import zuul.rpcclient

from zuul.lib import commandsocket
from zuul.lib import streamer_utils


COMMANDS = ['stop']


class RequestHandler(streamer_utils.BaseFingerRequestHandler):
    '''
    Class implementing the logic for handling a single finger request.
    '''

    log = logging.getLogger("zuul.fingergw")

    def __init__(self, *args, **kwargs):
        self.rpc = kwargs.pop('rpc')
        super(RequestHandler, self).__init__(*args, **kwargs)

    def _fingerClient(self, server, port, build_uuid):
        '''
        Open a finger connection and return all streaming results.

        :param server: The remote server.
        :param port: The remote port.
        :param build_uuid: The build UUID to stream.

        Both IPv4 and IPv6 are supported.
        '''
        with socket.create_connection((server, port), timeout=10) as s:
            # timeout only on the connection, let recv() wait forever
            s.settimeout(None)
            msg = "%s\n" % build_uuid    # Must have a trailing newline!
            s.sendall(msg.encode('utf-8'))
            while True:
                data = s.recv(1024)
                if data:
                    self.request.sendall(data)
                else:
                    break

    def handle(self):
        '''
        This method is called by the socketserver framework to handle an
        incoming request.
        '''
        try:
            build_uuid = self.getCommand()
            port_location = self.rpc.get_job_log_stream_address(build_uuid)

            if not port_location:
                msg = 'Invalid build UUID %s' % build_uuid
                self.request.sendall(msg.encode('utf-8'))
                return

            self._fingerClient(
                port_location['server'],
                port_location['port'],
                build_uuid,
            )
        except BrokenPipeError:   # Client disconnect
            return
        except Exception:
            self.log.exception('Finger request handling exception:')
            msg = 'Internal streaming error'
            self.request.sendall(msg.encode('utf-8'))
            return


class FingerGateway(object):
    '''
    Class implementing the finger multiplexing/gateway logic.

    For each incoming finger request, a new thread is started that will
    be responsible for finding which Zuul executor is executing the
    requested build (by asking Gearman), forwarding the request to that
    executor, and streaming the results back to our client.
    '''

    log = logging.getLogger("zuul.fingergw")

    def __init__(self, gearman, address, user, command_socket, pid_file):
        '''
        Initialize the finger gateway.

        :param tuple gearman: Gearman connection information. This should
            include the server, port, SSL key, SSL cert, and SSL CA.
        :param tuple address: The address and port to bind to for our gateway.
        :param str user: The user to which we should drop privileges after
            binding to our address.
        :param str command_socket: Path to the daemon command socket.
        :param str pid_file: Path to the daemon PID file.
        '''
        self.gear_server = gearman[0]
        self.gear_port = gearman[1]
        self.gear_ssl_key = gearman[2]
        self.gear_ssl_cert = gearman[3]
        self.gear_ssl_ca = gearman[4]
        self.address = address
        self.user = user
        self.pid_file = pid_file

        self.rpc = None
        self.server = None
        self.server_thread = None

        self.command_thread = None
        self.command_running = False
        self.command_socket = command_socket

        self.command_map = dict(
            stop=self.stop,
        )

    def _runCommand(self):
        while self.command_running:
            try:
                command = self.command_socket.get().decode('utf8')
                if command != '_stop':
                    self.command_map[command]()
                else:
                    return
            except Exception:
                self.log.exception("Exception while processing command")

    def _run(self):
        try:
            self.server.serve_forever()
        except Exception:
            self.log.exception('Abnormal termination:')
            raise

    def start(self):
        self.rpc = zuul.rpcclient.RPCClient(
            self.gear_server,
            self.gear_port,
            self.gear_ssl_key,
            self.gear_ssl_cert,
            self.gear_ssl_ca)

        self.server = streamer_utils.CustomThreadingTCPServer(
            self.address,
            functools.partial(RequestHandler, rpc=self.rpc),
            user=self.user,
            pid_file=self.pid_file)

        # Start the command processor after the server and privilege drop
        if self.command_socket:
            self.log.debug("Starting command processor")
            self.command_socket = commandsocket.CommandSocket(
                self.command_socket)
            self.command_socket.start()
            self.command_running = True
            self.command_thread = threading.Thread(
                target=self._runCommand, name='command')
            self.command_thread.daemon = True
            self.command_thread.start()

        # The socketserver shutdown() call will hang unless the call
        # to server_forever() happens in another thread. So let's do that.
        self.server_thread = threading.Thread(target=self._run)
        self.server_thread.daemon = True
        self.server_thread.start()
        self.log.info("Finger gateway is started")

    def stop(self):
        if self.command_socket:
            self.command_running = False
            try:
                self.command_socket.stop()
            except Exception:
                self.log.exception("Error stopping command socket:")

        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
            except Exception:
                self.log.exception("Error stopping TCP server:")

        if self.rpc:
            try:
                self.rpc.shutdown()
                self.rpc = None
            except Exception:
                self.log.exception("Error stopping RCP client:")

        self.log.info("Finger gateway is stopped")

    def wait(self):
        '''
        Wait on the gateway to shutdown.
        '''
        self.server_thread.join()
