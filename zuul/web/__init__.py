#!/usr/bin/env python
# Copyright (c) 2017 Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import asyncio
import codecs
import copy
import json
import logging
import os
import time
import uvloop

import aiohttp
from aiohttp import web

import zuul.model
import zuul.rpcclient
from zuul.web.handler import StaticHandler

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')


class LogStreamingHandler(object):
    log = logging.getLogger("zuul.web.LogStreamingHandler")

    def __init__(self, rpc):
        self.rpc = rpc

    def setEventLoop(self, event_loop):
        self.event_loop = event_loop

    async def _fingerClient(self, ws, server, port, job_uuid):
        """
        Create a client to connect to the finger streamer and pull results.

        :param aiohttp.web.WebSocketResponse ws: The websocket response object.
        :param str server: The executor server running the job.
        :param str port: The executor server port.
        :param str job_uuid: The job UUID to stream.
        """
        self.log.debug("Connecting to finger server %s:%s", server, port)
        reader, writer = await asyncio.open_connection(host=server, port=port,
                                                       loop=self.event_loop)

        self.log.debug("Sending finger request for %s", job_uuid)
        msg = "%s\n" % job_uuid    # Must have a trailing newline!

        writer.write(msg.encode('utf8'))
        await writer.drain()

        Decoder = codecs.getincrementaldecoder('utf8')
        decoder = Decoder()

        while True:
            data = await reader.read(1024)
            if data:
                data = decoder.decode(data)
                if data:
                    await ws.send_str(data)
            else:
                # Make sure we flush anything left in the decoder
                data = decoder.decode(b'', final=True)
                if data:
                    await ws.send_str(data)
                writer.close()
                return

    async def _streamLog(self, ws, request):
        """
        Stream the log for the requested job back to the client.

        :param aiohttp.web.WebSocketResponse ws: The websocket response object.
        :param dict request: The client request parameters.
        """
        for key in ('uuid', 'logfile'):
            if key not in request:
                return (4000, "'{key}' missing from request payload".format(
                        key=key))

        # Schedule the blocking gearman work in an Executor
        gear_task = self.event_loop.run_in_executor(
            None,
            self.rpc.get_job_log_stream_address,
            request['uuid'],
        )

        try:
            port_location = await asyncio.wait_for(gear_task, 10)
        except asyncio.TimeoutError:
            return (4010, "Gearman timeout")

        if not port_location:
            return (4011, "Error with Gearman")

        try:
            await self._fingerClient(
                ws, port_location['server'], port_location['port'],
                request['uuid']
            )
        except Exception as e:
            self.log.exception("Finger client exception:")
            await ws.send_str("Failure from finger client: %s" % e)

        return (1000, "No more data")

    async def processRequest(self, request):
        """
        Handle a client websocket request for log streaming.

        :param aiohttp.web.Request request: The client request.
        """
        try:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    req = json.loads(msg.data)
                    self.log.debug("Websocket request: %s", req)
                    code, msg = await self._streamLog(ws, req)

                    # We expect to process only a single message. I.e., we
                    # can stream only a single file at a time.
                    await ws.close(code=code, message=msg)
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.log.error(
                        "Websocket connection closed with exception %s",
                        ws.exception()
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
        except asyncio.CancelledError:
            self.log.debug("Websocket request handling cancelled")
            pass
        except Exception as e:
            self.log.exception("Websocket exception:")
            await ws.close(code=4009, message=str(e).encode('utf-8'))
        return ws


class GearmanHandler(object):
    log = logging.getLogger("zuul.web.GearmanHandler")

    # Tenant status cache expiry
    cache_expiry = 1

    def __init__(self, rpc):
        self.rpc = rpc
        self.cache = {}
        self.cache_time = {}
        self.controllers = {
            'tenant_list': self.tenant_list,
            'status_get': self.status_get,
            'job_list': self.job_list,
            'key_get': self.key_get,
        }

    def setEventLoop(self, event_loop):
        self.event_loop = event_loop

    # TODO: At some point, we should make this use a gear.Client, rather than
    # the RPC client, so we can use that to make async Gearman calls. This
    # implementation will create additional threads by putting the call onto
    # the asycio ThreadPool, which is not ideal.
    async def asyncSubmitJob(self, name, data):
        '''
        Submit a job to Gearman asynchronously.

        This will raise a asyncio.TimeoutError if we hit the timeout. It is
        up to the caller to handle the exception.
        '''
        gear_task = self.event_loop.run_in_executor(
            None, self.rpc.submitJob, name, data)
        job = await asyncio.wait_for(gear_task, 300)
        return job

    async def tenant_list(self, request, result_filter=None):
        job = await self.asyncSubmitJob('zuul:tenant_list', {})
        return web.json_response(json.loads(job.data[0]))

    async def status_get(self, request, result_filter=None):
        tenant = request.match_info["tenant"]
        if tenant not in self.cache or \
           (time.time() - self.cache_time[tenant]) > self.cache_expiry:
            job = await self.asyncSubmitJob('zuul:status_get',
                                            {'tenant': tenant})
            self.cache[tenant] = json.loads(job.data[0])
            self.cache_time[tenant] = time.time()
        payload = self.cache[tenant]
        if payload.get('code') == 404:
            return web.HTTPNotFound(reason=payload['message'])
        if result_filter:
            payload = result_filter.filterPayload(payload)
        resp = web.json_response(payload)
        resp.headers["Cache-Control"] = "public, max-age=%d" % \
                                        self.cache_expiry
        resp.last_modified = self.cache_time[tenant]
        return resp

    async def job_list(self, request, result_filter=None):
        tenant = request.match_info["tenant"]
        job = await self.asyncSubmitJob('zuul:job_list', {'tenant': tenant})
        return web.json_response(json.loads(job.data[0]))

    async def key_get(self, request, result_filter=None):
        tenant = request.match_info["tenant"]
        project = request.match_info["project"]
        job = await self.asyncSubmitJob('zuul:key_get', {'tenant': tenant,
                                                         'project': project})
        return web.Response(body=job.data[0])

    async def processRequest(self, request, action, result_filter=None):
        resp = None
        try:
            resp = await self.controllers[action](request, result_filter)
            resp.headers['Access-Control-Allow-Origin'] = '*'
        except asyncio.CancelledError:
            self.log.debug("request handling cancelled")
        except Exception as e:
            self.log.exception("exception:")
            resp = web.json_response({'error_description': 'Internal error'},
                                     status=500)
        return resp


class ChangeFilter(object):
    def __init__(self, desired):
        self.desired = desired

    def filterPayload(self, payload):
        status = []
        for pipeline in payload['pipelines']:
            for change_queue in pipeline['change_queues']:
                for head in change_queue['heads']:
                    for change in head:
                        if self.wantChange(change):
                            status.append(copy.deepcopy(change))
        return status

    def wantChange(self, change):
        return change['id'] == self.desired


class ZuulWeb(object):

    log = logging.getLogger("zuul.web.ZuulWeb")

    def __init__(self, listen_address, listen_port,
                 gear_server, gear_port,
                 ssl_key=None, ssl_cert=None, ssl_ca=None,
                 static_cache_expiry=3600,
                 connections=None,
                 _connections=None,
                 info=None,
                 static_path=None):
        self.start_time = time.time()
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.event_loop = None
        self.term = None
        self.server = None
        self.static_cache_expiry = static_cache_expiry
        self.info = info
        self.static_path = static_path or STATIC_DIR
        # instanciate handlers
        self.rpc = zuul.rpcclient.RPCClient(gear_server, gear_port,
                                            ssl_key, ssl_cert, ssl_ca)
        self.log_streaming_handler = LogStreamingHandler(self.rpc)
        self.gearman_handler = GearmanHandler(self.rpc)
        self._plugin_routes = []  # type: List[zuul.web.handler.BaseWebHandler]
        self._connection_handlers = []
        connections = connections or []
        for connection in connections:
            self._connection_handlers.extend(
                connection.getWebHandlers(self, self.info))
        self.connections = _connections
        self._plugin_routes.extend(self._connection_handlers)

    async def _handleWebsocket(self, request):
        return await self.log_streaming_handler.processRequest(
            request)

    def _handleRootInfo(self, request):
        return self._handleInfo(self.info)

    def _handleTenantInfo(self, request):
        info = self.info.copy()
        info.tenant = request.match_info["tenant"]
        return self._handleInfo(info)

    def _handleInfo(self, info):
        resp = web.json_response({'info': info.toDict()}, status=200)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        if self.static_cache_expiry:
            resp.headers['Cache-Control'] = "public, max-age=%d" % \
                self.static_cache_expiry
        resp.last_modified = self.start_time
        return resp

    async def _handleTenantsRequest(self, request):
        return await self.gearman_handler.processRequest(request,
                                                         'tenant_list')

    async def _handleStatusRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'status_get')

    async def _handleStatusChangeRequest(self, request):
        change = request.match_info["change"]
        return await self.gearman_handler.processRequest(
            request, 'status_get', ChangeFilter(change))

    async def _handleJobsRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'job_list')

    async def _handleKeyRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'key_get')

    async def _handleStatic(self, request):
        # http://example.com//status.html comes in as '/status.html'
        target_path = request.match_info['path'].lstrip('/')
        fs_path = os.path.abspath(os.path.join(self.static_path, target_path))
        if not fs_path.startswith(os.path.abspath(self.static_path)):
            return web.HTTPForbidden()
        if not os.path.exists(fs_path):
            return web.HTTPNotFound()
        return web.FileResponse(fs_path)

    def run(self, loop=None):
        """
        Run the websocket daemon.

        Because this method can be the target of a new thread, we need to
        set the thread event loop here, rather than in __init__().

        :param loop: The event loop to use. If not supplied, the default main
            thread event loop is used. This should be supplied if ZuulWeb
            is run within a separate (non-main) thread.
        """
        sql_driver = self.connections.drivers['sql']
        routes = [
            ('GET', '/api/info', self._handleRootInfo),
            ('GET', '/api/tenants', self._handleTenantsRequest),
            ('GET', '/api/tenant/{tenant}/info', self._handleTenantInfo),
            ('GET', '/api/tenant/{tenant}/status', self._handleStatusRequest),
            ('GET', '/api/tenant/{tenant}/jobs', self._handleJobsRequest),
            ('GET', '/api/tenant/{tenant}/status/change/{change}',
             self._handleStatusChangeRequest),
            ('GET', '/api/tenant/{tenant}/console-stream',
             self._handleWebsocket),
            ('GET', '/api/tenant/{tenant}/key/{project:.*}.pub',
             self._handleKeyRequest),
            ('GET', '/api/tenant/{tenant}/builds',
             sql_driver.handleRequest),
        ]

        static_routes = [
            StaticHandler(self, '/t/{tenant}/', 'status.html'),
            StaticHandler(self, '/', 'tenants.html'),
        ]

        for route in static_routes + self._plugin_routes:
            routes.append((route.method, route.path, route.handleRequest))

        # Add fallthrough routes at the end for the static html/js files
        routes.append(('GET', '/t/{tenant}/{path:.*}', self._handleStatic))
        routes.append(('GET', '/{path:.*}', self._handleStatic))

        self.log.debug("ZuulWeb starting")
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        user_supplied_loop = loop is not None
        if not loop:
            loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)

        self.event_loop = loop
        self.log_streaming_handler.setEventLoop(loop)
        self.gearman_handler.setEventLoop(loop)
        sql_driver.setEventLoop(loop)

        for handler in self._connection_handlers:
            if hasattr(handler, 'setEventLoop'):
                handler.setEventLoop(loop)

        app = web.Application()
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)
        handler = app.make_handler(loop=self.event_loop)

        # create the server
        coro = self.event_loop.create_server(handler,
                                             self.listen_address,
                                             self.listen_port)
        self.server = self.event_loop.run_until_complete(coro)

        self.term = asyncio.Future()

        # start the server
        self.event_loop.run_until_complete(self.term)

        # cleanup
        self.log.debug("ZuulWeb stopping")
        self.server.close()
        self.event_loop.run_until_complete(self.server.wait_closed())
        self.event_loop.run_until_complete(app.shutdown())
        self.event_loop.run_until_complete(handler.shutdown(60.0))
        self.event_loop.run_until_complete(app.cleanup())
        self.log.debug("ZuulWeb stopped")

        # Only run these if we are controlling the loop - they need to be
        # run from the main thread
        if not user_supplied_loop:
            loop.stop()
            loop.close()

        self.rpc.shutdown()

    def stop(self):
        if self.event_loop and self.term:
            self.event_loop.call_soon_threadsafe(self.term.set_result, True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    z = ZuulWeb(listen_address="127.0.0.1", listen_port=9000,
                gear_server="127.0.0.1", gear_port=4730)
    z.run(loop)
