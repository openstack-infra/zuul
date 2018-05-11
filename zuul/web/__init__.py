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


import cherrypy
import socket
from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool
from ws4py.websocket import WebSocket
import codecs
import copy
import json
import logging
import os
import time

import zuul.model
import zuul.rpcclient

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
cherrypy.tools.websocket = WebSocketTool()


class SaveParamsTool(cherrypy.Tool):
    """
    Save the URL parameters to allow them to take precedence over query
    string parameters.
    """
    def __init__(self):
        cherrypy.Tool.__init__(self, 'on_start_resource',
                               self.saveParams)

    def _setup(self):
        cherrypy.Tool._setup(self)
        cherrypy.request.hooks.attach('before_handler',
                                      self.restoreParams)

    def saveParams(self, restore=True):
        cherrypy.request.url_params = cherrypy.request.params.copy()
        cherrypy.request.url_params_restore = restore

    def restoreParams(self):
        if cherrypy.request.url_params_restore:
            cherrypy.request.params.update(cherrypy.request.url_params)


cherrypy.tools.save_params = SaveParamsTool()


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


class LogStreamHandler(WebSocket):
    log = logging.getLogger("zuul.web")

    def received_message(self, message):
        if message.is_text:
            req = json.loads(message.data.decode('utf-8'))
            self.log.debug("Websocket request: %s", req)
            code, msg = self._streamLog(req)
            self.log.debug("close Websocket request: %s %s", code, msg)
            self.close(code, msg)

    def _streamLog(self, request):
        """
        Stream the log for the requested job back to the client.

        :param dict request: The client request parameters.
        """
        for key in ('uuid', 'logfile'):
            if key not in request:
                return (4000, "'{key}' missing from request payload".format(
                        key=key))

        port_location = self.rpc.get_job_log_stream_address(request['uuid'])
        if not port_location:
            return (4011, "Error with Gearman")

        self._fingerClient(
            port_location['server'], port_location['port'],
            request['uuid'])

        return (1000, "No more data")

    def _fingerClient(self, server, port, build_uuid):
        """
        Create a client to connect to the finger streamer and pull results.

        :param str server: The executor server running the job.
        :param str port: The executor server port.
        :param str build_uuid: The build UUID to stream.
        """
        self.log.debug("Connecting to finger server %s:%s", server, port)
        Decoder = codecs.getincrementaldecoder('utf8')
        decoder = Decoder()
        with socket.create_connection((server, port), timeout=10) as s:
            # timeout only on the connection, let recv() wait forever
            s.settimeout(None)
            msg = "%s\n" % build_uuid    # Must have a trailing newline!
            s.sendall(msg.encode('utf-8'))
            while True:
                data = s.recv(1024)
                if data:
                    data = decoder.decode(data)
                    if data:
                        self.send(data, False)
                else:
                    # Make sure we flush anything left in the decoder
                    data = decoder.decode(b'', final=True)
                    if data:
                        self.send(data, False)
                    self.close()
                    return


class ZuulWebAPI(object):
    log = logging.getLogger("zuul.web")

    def __init__(self, zuulweb):
        self.rpc = zuulweb.rpc
        self.zuulweb = zuulweb
        self.cache = {}
        self.cache_time = {}
        self.cache_expiry = 1
        self.static_cache_expiry = zuulweb.static_cache_expiry

    @cherrypy.expose
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def info(self):
        return self._handleInfo(self.zuulweb.info)

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def tenant_info(self, tenant):
        info = self.zuulweb.info.copy()
        info.tenant = tenant
        return self._handleInfo(info)

    def _handleInfo(self, info):
        ret = {'info': info.toDict()}
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        if self.static_cache_expiry:
            resp.headers['Cache-Control'] = "public, max-age=%d" % \
                self.static_cache_expiry
        resp.last_modified = self.zuulweb.start_time
        return ret

    @cherrypy.expose
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def tenants(self):
        job = self.rpc.submitJob('zuul:tenant_list', {})
        ret = json.loads(job.data[0])
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    def _getStatus(self, tenant):
        if tenant not in self.cache or \
           (time.time() - self.cache_time[tenant]) > self.cache_expiry:
            job = self.rpc.submitJob('zuul:status_get',
                                     {'tenant': tenant})
            self.cache[tenant] = json.loads(job.data[0])
            self.cache_time[tenant] = time.time()
        payload = self.cache[tenant]
        if payload.get('code') == 404:
            raise cherrypy.HTTPError(404, payload['message'])
        resp = cherrypy.response
        resp.headers["Cache-Control"] = "public, max-age=%d" % \
                                        self.cache_expiry
        resp.headers["Last-modified"] = self.cache_time[tenant]
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return payload

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def status(self, tenant):
        return self._getStatus(tenant)

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def status_change(self, tenant, change):
        payload = self._getStatus(tenant)
        result_filter = ChangeFilter(change)
        return result_filter.filterPayload(payload)

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def jobs(self, tenant):
        job = self.rpc.submitJob('zuul:job_list', {'tenant': tenant})
        ret = json.loads(job.data[0])
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    def key(self, tenant, project):
        job = self.rpc.submitJob('zuul:key_get', {'tenant': tenant,
                                                  'project': project})
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return job.data[0]

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def builds(self, tenant, project=None, pipeline=None, change=None,
               branch=None, patchset=None, ref=None, newrev=None,
               uuid=None, job_name=None, voting=None, node_name=None,
               result=None, limit=50, skip=0):
        sql_driver = self.zuulweb.connections.drivers['sql']
        connection = sql_driver.tenant_connections.get(tenant)
        if not connection:
            raise Exception("Unable to find connection for tenant %s" % tenant)

        args = {
            'buildset_filters': {'tenant': [tenant]},
            'build_filters': {},
            'limit': limit,
            'skip': skip,
        }

        for k in ("project", "pipeline", "change", "branch",
                  "patchset", "ref", "newrev"):
            v = locals()[k]
            if v:
                args['buildset_filters'].setdefault(k, []).append(v)
        for k in ("uuid", "job_name", "voting", "node_name",
                  "result"):
            v = locals()[k]
            if v:
                args['build_filters'].setdefault(k, []).append(v)
        data = connection.get_builds(args)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return data

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.websocket(handler_cls=LogStreamHandler)
    def console_stream(self, tenant):
        cherrypy.request.ws_handler.rpc = self.rpc


class TenantStaticHandler(object):
    def __init__(self, path):
        self._cp_config = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': path,
            'tools.staticdir.index': 'status.html',
        }


class RootStaticHandler(object):
    def __init__(self, path):
        self._cp_config = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': path,
            'tools.staticdir.index': 'tenants.html',
        }


class ZuulWeb(object):
    log = logging.getLogger("zuul.web.ZuulWeb")

    def __init__(self, listen_address, listen_port,
                 gear_server, gear_port,
                 ssl_key=None, ssl_cert=None, ssl_ca=None,
                 static_cache_expiry=3600,
                 connections=None,
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
        self.static_path = os.path.abspath(static_path or STATIC_DIR)
        # instanciate handlers
        self.rpc = zuul.rpcclient.RPCClient(gear_server, gear_port,
                                            ssl_key, ssl_cert, ssl_ca)
        self.connections = connections

        route_map = cherrypy.dispatch.RoutesDispatcher()
        api = ZuulWebAPI(self)
        tenant_static = TenantStaticHandler(self.static_path)
        root_static = RootStaticHandler(self.static_path)
        route_map.connect('api', '/api/info',
                          controller=api, action='info')
        route_map.connect('api', '/api/tenants',
                          controller=api, action='tenants')
        route_map.connect('api', '/api/tenant/{tenant}/info',
                          controller=api, action='tenant_info')
        route_map.connect('api', '/api/tenant/{tenant}/status',
                          controller=api, action='status')
        route_map.connect('api', '/api/tenant/{tenant}/status/change/{change}',
                          controller=api, action='status_change')
        route_map.connect('api', '/api/tenant/{tenant}/jobs',
                          controller=api, action='jobs')
        route_map.connect('api', '/api/tenant/{tenant}/key/{project:.*}.pub',
                          controller=api, action='key')
        route_map.connect('api', '/api/tenant/{tenant}/console-stream',
                          controller=api, action='console_stream')
        route_map.connect('api', '/api/tenant/{tenant}/builds',
                          controller=api, action='builds')

        for connection in connections.connections.values():
            controller = connection.getWebController(self, self.info)
            if controller:
                cherrypy.tree.mount(
                    controller,
                    '/api/connection/%s' % connection.connection_name)

        # Add fallthrough routes at the end for the static html/js files
        route_map.connect('root_static', '/{path:.*}',
                          controller=root_static, action='default')
        route_map.connect('tenant_static', '/t/{tenant}/{path:.*}',
                          controller=tenant_static, action='default')

        conf = {
            '/': {
                'request.dispatch': route_map
            }
        }
        cherrypy.config.update({
            'global': {
                'environment': 'production',
                'server.socket_host': listen_address,
                'server.socket_port': listen_port,
            },
        })

        cherrypy.tree.mount(api, '/', config=conf)

    @property
    def port(self):
        return cherrypy.server.bound_addr[1]

    def start(self):
        self.log.debug("ZuulWeb starting")
        self.wsplugin = WebSocketPlugin(cherrypy.engine)
        self.wsplugin.subscribe()
        cherrypy.engine.start()

    def stop(self):
        self.log.debug("ZuulWeb stopping")
        self.rpc.shutdown()
        cherrypy.engine.exit()
        # Not strictly necessary, but without this, if the server is
        # started again (e.g., in the unit tests) it will reuse the
        # same host/port settings.
        cherrypy.server.httpserver = None
        self.wsplugin.unsubscribe()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    import zuul.lib.connections
    connections = zuul.lib.connections.ConnectionRegistry()
    z = ZuulWeb(listen_address="127.0.0.1", listen_port=9000,
                gear_server="127.0.0.1", gear_port=4730,
                connections=connections)
    z.start()
    cherrypy.engine.block()
