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
import json
import logging
import os
import time
import urllib.parse
import uvloop

import aiohttp
from aiohttp import web

from sqlalchemy.sql import select

import zuul.rpcclient

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

        while True:
            data = await reader.read(1024)
            if data:
                await ws.send_str(data.decode('utf8'))
            else:
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
            msg = "Failure from finger client: %s" % e
            await ws.send_str(msg.decode('utf8'))

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

    def tenant_list(self, request):
        job = self.rpc.submitJob('zuul:tenant_list', {})
        return web.json_response(json.loads(job.data[0]))

    def status_get(self, request):
        tenant = request.match_info["tenant"]
        if tenant not in self.cache or \
           (time.time() - self.cache_time[tenant]) > self.cache_expiry:
            job = self.rpc.submitJob('zuul:status_get', {'tenant': tenant})
            self.cache[tenant] = json.loads(job.data[0])
            self.cache_time[tenant] = time.time()
        resp = web.json_response(self.cache[tenant])
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers["Cache-Control"] = "public, max-age=%d" % \
                                        self.cache_expiry
        resp.last_modified = self.cache_time[tenant]
        return resp

    def job_list(self, request):
        tenant = request.match_info["tenant"]
        job = self.rpc.submitJob('zuul:job_list', {'tenant': tenant})
        resp = web.json_response(json.loads(job.data[0]))
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    def key_get(self, request):
        tenant = request.match_info["tenant"]
        project = request.match_info["project"]
        job = self.rpc.submitJob('zuul:key_get', {'tenant': tenant,
                                                  'project': project})
        return web.Response(body=job.data[0])

    async def processRequest(self, request, action):
        try:
            resp = self.controllers[action](request)
        except asyncio.CancelledError:
            self.log.debug("request handling cancelled")
        except Exception as e:
            self.log.exception("exception:")
            resp = web.json_response({'error_description': 'Internal error'},
                                     status=500)
        return resp


class SqlHandler(object):
    log = logging.getLogger("zuul.web.SqlHandler")
    filters = ("project", "pipeline", "change", "patchset", "ref",
               "result", "uuid", "job_name", "voting", "node_name", "newrev")

    def __init__(self, connection):
        self.connection = connection

    def query(self, args):
        build = self.connection.zuul_build_table
        buildset = self.connection.zuul_buildset_table
        query = select([
            buildset.c.project,
            buildset.c.pipeline,
            buildset.c.change,
            buildset.c.patchset,
            buildset.c.ref,
            buildset.c.newrev,
            buildset.c.ref_url,
            build.c.result,
            build.c.uuid,
            build.c.job_name,
            build.c.voting,
            build.c.node_name,
            build.c.start_time,
            build.c.end_time,
            build.c.log_url]).select_from(build.join(buildset))
        for table in ('build', 'buildset'):
            for k, v in args['%s_filters' % table].items():
                if table == 'build':
                    column = build.c
                else:
                    column = buildset.c
                query = query.where(getattr(column, k).in_(v))
        return query.limit(args['limit']).offset(args['skip']).order_by(
            build.c.id.desc())

    def get_builds(self, args):
        """Return a list of build"""
        builds = []
        with self.connection.engine.begin() as conn:
            query = self.query(args)
            for row in conn.execute(query):
                build = dict(row)
                # Convert date to iso format
                if row.start_time:
                    build['start_time'] = row.start_time.strftime(
                        '%Y-%m-%dT%H:%M:%S')
                if row.end_time:
                    build['end_time'] = row.end_time.strftime(
                        '%Y-%m-%dT%H:%M:%S')
                # Compute run duration
                if row.start_time and row.end_time:
                    build['duration'] = (row.end_time -
                                         row.start_time).total_seconds()
                builds.append(build)
        return builds

    async def processRequest(self, request):
        try:
            args = {
                'buildset_filters': {},
                'build_filters': {},
                'limit': 50,
                'skip': 0,
            }
            for k, v in urllib.parse.parse_qsl(request.rel_url.query_string):
                if k in ("tenant", "project", "pipeline", "change",
                         "patchset", "ref", "newrev"):
                    args['buildset_filters'].setdefault(k, []).append(v)
                elif k in ("uuid", "job_name", "voting", "node_name",
                           "result"):
                    args['build_filters'].setdefault(k, []).append(v)
                elif k in ("limit", "skip"):
                    args[k] = int(v)
                else:
                    raise ValueError("Unknown parameter %s" % k)
            data = self.get_builds(args)
            resp = web.json_response(data)
            resp.headers['Access-Control-Allow-Origin'] = '*'
        except Exception as e:
            self.log.exception("Jobs exception:")
            resp = web.json_response({'error_description': 'Internal error'},
                                     status=500)
        return resp


class ZuulWeb(object):

    log = logging.getLogger("zuul.web.ZuulWeb")

    def __init__(self, listen_address, listen_port,
                 gear_server, gear_port,
                 ssl_key=None, ssl_cert=None, ssl_ca=None,
                 static_cache_expiry=3600,
                 sql_connection=None):
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.event_loop = None
        self.term = None
        self.server = None
        self.static_cache_expiry = static_cache_expiry
        # instanciate handlers
        self.rpc = zuul.rpcclient.RPCClient(gear_server, gear_port,
                                            ssl_key, ssl_cert, ssl_ca)
        self.log_streaming_handler = LogStreamingHandler(self.rpc)
        self.gearman_handler = GearmanHandler(self.rpc)
        if sql_connection:
            self.sql_handler = SqlHandler(sql_connection)
        else:
            self.sql_handler = None

    async def _handleWebsocket(self, request):
        return await self.log_streaming_handler.processRequest(
            request)

    async def _handleTenantsRequest(self, request):
        return await self.gearman_handler.processRequest(request,
                                                         'tenant_list')

    async def _handleStatusRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'status_get')

    async def _handleJobsRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'job_list')

    async def _handleSqlRequest(self, request):
        return await self.sql_handler.processRequest(request)

    async def _handleKeyRequest(self, request):
        return await self.gearman_handler.processRequest(request, 'key_get')

    async def _handleStaticRequest(self, request):
        fp = None
        if request.path.endswith("tenants.html") or request.path.endswith("/"):
            fp = os.path.join(STATIC_DIR, "index.html")
        elif request.path.endswith("status.html"):
            fp = os.path.join(STATIC_DIR, "status.html")
        elif request.path.endswith("jobs.html"):
            fp = os.path.join(STATIC_DIR, "jobs.html")
        elif request.path.endswith("builds.html"):
            fp = os.path.join(STATIC_DIR, "builds.html")
        elif request.path.endswith("stream.html"):
            fp = os.path.join(STATIC_DIR, "stream.html")
        headers = {}
        if self.static_cache_expiry:
            headers['Cache-Control'] = "public, max-age=%d" % \
                self.static_cache_expiry
        return web.FileResponse(fp, headers=headers)

    def run(self, loop=None):
        """
        Run the websocket daemon.

        Because this method can be the target of a new thread, we need to
        set the thread event loop here, rather than in __init__().

        :param loop: The event loop to use. If not supplied, the default main
            thread event loop is used. This should be supplied if ZuulWeb
            is run within a separate (non-main) thread.
        """
        routes = [
            ('GET', '/tenants.json', self._handleTenantsRequest),
            ('GET', '/{tenant}/status.json', self._handleStatusRequest),
            ('GET', '/{tenant}/jobs.json', self._handleJobsRequest),
            ('GET', '/{tenant}/console-stream', self._handleWebsocket),
            ('GET', '/{tenant}/{project:.*}.pub', self._handleKeyRequest),
            ('GET', '/{tenant}/status.html', self._handleStaticRequest),
            ('GET', '/{tenant}/jobs.html', self._handleStaticRequest),
            ('GET', '/{tenant}/stream.html', self._handleStaticRequest),
            ('GET', '/tenants.html', self._handleStaticRequest),
            ('GET', '/', self._handleStaticRequest),
        ]

        if self.sql_handler:
            routes.append(('GET', '/{tenant}/builds.json',
                           self._handleSqlRequest))
            routes.append(('GET', '/{tenant}/builds.html',
                           self._handleStaticRequest))

        self.log.debug("ZuulWeb starting")
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        user_supplied_loop = loop is not None
        if not loop:
            loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)

        self.event_loop = loop
        self.log_streaming_handler.setEventLoop(loop)

        app = web.Application()
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)
        app.router.add_static('/static', STATIC_DIR)
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
