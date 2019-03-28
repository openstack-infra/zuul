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
from datetime import datetime
import json
import logging
import os
import time
import select
import threading

import zuul.model
import zuul.rpcclient
import zuul.zk

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

    def __init__(self, *args, **kw):
        kw['heartbeat_freq'] = 20
        super(LogStreamHandler, self).__init__(*args, **kw)
        self.streamer = None

    def received_message(self, message):
        if message.is_text:
            req = json.loads(message.data.decode('utf-8'))
            self.log.debug("Websocket request: %s", req)
            if self.streamer:
                self.log.debug("Ignoring request due to existing streamer")
                return
            try:
                self._streamLog(req)
            except Exception:
                self.log.exception("Error processing websocket message:")
                raise

    def closed(self, code, reason=None):
        self.log.debug("Websocket closed: %s %s", code, reason)
        if self.streamer:
            try:
                self.streamer.zuulweb.stream_manager.unregisterStreamer(
                    self.streamer)
            except Exception:
                self.log.exception("Error on remote websocket close:")

    def logClose(self, code, msg):
        self.log.debug("Websocket close: %s %s", code, msg)
        try:
            self.close(code, msg)
        except Exception:
            self.log.exception("Error closing websocket:")

    def _streamLog(self, request):
        """
        Stream the log for the requested job back to the client.

        :param dict request: The client request parameters.
        """
        for key in ('uuid', 'logfile'):
            if key not in request:
                return self.logClose(
                    4000,
                    "'{key}' missing from request payload".format(
                        key=key))

        port_location = self.zuulweb.rpc.get_job_log_stream_address(
            request['uuid'])
        if not port_location:
            return self.logClose(4011, "Error with Gearman")

        self.streamer = LogStreamer(
            self.zuulweb, self,
            port_location['server'], port_location['port'],
            request['uuid'])


class LogStreamer(object):
    log = logging.getLogger("zuul.web")

    def __init__(self, zuulweb, websocket, server, port, build_uuid):
        """
        Create a client to connect to the finger streamer and pull results.

        :param str server: The executor server running the job.
        :param str port: The executor server port.
        :param str build_uuid: The build UUID to stream.
        """
        self.log.debug("Connecting to finger server %s:%s", server, port)
        Decoder = codecs.getincrementaldecoder('utf8')
        self.decoder = Decoder()
        self.finger_socket = socket.create_connection(
            (server, port), timeout=10)
        self.finger_socket.settimeout(None)
        self.websocket = websocket
        self.zuulweb = zuulweb
        self.uuid = build_uuid
        msg = "%s\n" % build_uuid    # Must have a trailing newline!
        self.finger_socket.sendall(msg.encode('utf-8'))
        self.zuulweb.stream_manager.registerStreamer(self)

    def __repr__(self):
        return '<LogStreamer %s uuid:%s>' % (self.websocket, self.uuid)

    def errorClose(self):
        self.websocket.logClose(4011, "Unknown error")

    def handle(self, event):
        if event & select.POLLIN:
            data = self.finger_socket.recv(1024)
            if data:
                data = self.decoder.decode(data)
                if data:
                    self.websocket.send(data, False)
            else:
                # Make sure we flush anything left in the decoder
                data = self.decoder.decode(b'', final=True)
                if data:
                    self.websocket.send(data, False)
                self.zuulweb.stream_manager.unregisterStreamer(self)
                self.finger_socket.close()
                return self.websocket.logClose(1000, "No more data")
        else:
            self.zuulweb.stream_manager.unregisterStreamer(self)
            self.finger_socket.close()
            return self.websocket.logClose(1000, "Remote error")


class ZuulWebAPI(object):
    log = logging.getLogger("zuul.web")

    def __init__(self, zuulweb):
        self.rpc = zuulweb.rpc
        self.zk = zuulweb.zk
        self.zuulweb = zuulweb
        self.cache = {}
        self.cache_time = {}
        self.cache_expiry = 1
        self.static_cache_expiry = zuulweb.static_cache_expiry
        self.status_lock = threading.Lock()

    @cherrypy.expose
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def index(self):
        return {
            'info': '/api/info',
            'connections': '/api/connections',
            'tenants': '/api/tenants',
            'tenant_info': '/api/tenant/{tenant}/info',
            'status': '/api/tenant/{tenant}/status',
            'status_change': '/api/tenant/{tenant}/status/change/{change}',
            'jobs': '/api/tenant/{tenant}/jobs',
            'job': '/api/tenant/{tenant}/job/{job_name}',
            'projects': '/api/tenant/{tenant}/projects',
            'project': '/api/tenant/{tenant}/project/{project:.*}',
            'project_freeze_jobs': '/api/tenant/{tenant}/pipeline/{pipeline}/'
                                   'project/{project:.*}/branch/{branch:.*}/'
                                   'freeze-jobs',
            'pipelines': '/api/tenant/{tenant}/pipelines',
            'labels': '/api/tenant/{tenant}/labels',
            'nodes': '/api/tenant/{tenant}/nodes',
            'key': '/api/tenant/{tenant}/key/{project:.*}.pub',
            'project_ssh_key': '/api/tenant/{tenant}/project-ssh-key/'
                               '{project:.*}.pub',
            'console_stream': '/api/tenant/{tenant}/console-stream',
            'builds': '/api/tenant/{tenant}/builds',
            'build': '/api/tenant/{tenant}/build/{uuid}',
            'buildsets': '/api/tenant/{tenant}/buildsets',
            'buildset': '/api/tenant/{tenant}/buildset/{uuid}',
            'config_errors': '/api/tenant/{tenant}/config-errors',
        }

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

    @cherrypy.expose
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def connections(self):
        job = self.rpc.submitJob('zuul:connection_list', {})
        ret = json.loads(job.data[0])
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    def _getStatus(self, tenant):
        with self.status_lock:
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
        last_modified = datetime.utcfromtimestamp(self.cache_time[tenant])
        last_modified_header = last_modified.strftime('%a, %d %b %Y %X GMT')
        resp.headers["Last-modified"] = last_modified_header
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
        if ret is None:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def config_errors(self, tenant):
        config_errors = self.rpc.submitJob(
            'zuul:config_errors_list', {'tenant': tenant})
        ret = json.loads(config_errors.data[0])
        if ret is None:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def job(self, tenant, job_name):
        job = self.rpc.submitJob(
            'zuul:job_get', {'tenant': tenant, 'job': job_name})
        ret = json.loads(job.data[0])
        if not ret:
            raise cherrypy.HTTPError(404, 'Job %s does not exist.' % job_name)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def projects(self, tenant):
        job = self.rpc.submitJob('zuul:project_list', {'tenant': tenant})
        ret = json.loads(job.data[0])
        if ret is None:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def project(self, tenant, project):
        job = self.rpc.submitJob(
            'zuul:project_get', {'tenant': tenant, 'project': project})
        ret = json.loads(job.data[0])
        if ret is None:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)
        if not ret:
            raise cherrypy.HTTPError(
                404, 'Project %s does not exist.' % project)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def pipelines(self, tenant):
        job = self.rpc.submitJob('zuul:pipeline_list', {'tenant': tenant})
        ret = json.loads(job.data[0])
        if ret is None:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def labels(self, tenant):
        labels = set()
        for launcher in self.zk.getRegisteredLaunchers():
            for label in launcher.supported_labels:
                labels.add(label)
        ret = [{'name': label} for label in sorted(labels)]
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def nodes(self, tenant):
        ret = []
        for node in self.zk.nodeIterator():
            node_data = {}
            for key in ("id", "type", "connection_type", "external_id",
                        "provider", "state", "state_time", "comment"):
                node_data[key] = node.get(key)
            ret.append(node_data)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    def key(self, tenant, project):
        job = self.rpc.submitJob('zuul:key_get', {'tenant': tenant,
                                                  'project': project,
                                                  'key': 'secrets'})
        if not job.data:
            raise cherrypy.HTTPError(
                404, 'Project %s does not exist.' % project)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Content-Type'] = 'text/plain'
        return job.data[0]

    @cherrypy.expose
    @cherrypy.tools.save_params()
    def project_ssh_key(self, tenant, project):
        job = self.rpc.submitJob('zuul:key_get', {'tenant': tenant,
                                                  'project': project,
                                                  'key': 'ssh'})
        if not job.data:
            raise cherrypy.HTTPError(
                404, 'Project %s does not exist.' % project)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Content-Type'] = 'text/plain'
        return job.data[0] + '\n'

    def buildToDict(self, build, buildset=None):
        start_time = build.start_time
        if build.start_time:
            start_time = start_time.strftime(
                '%Y-%m-%dT%H:%M:%S')
        end_time = build.end_time
        if build.end_time:
            end_time = end_time.strftime(
                '%Y-%m-%dT%H:%M:%S')
        if build.start_time and build.end_time:
            duration = (build.end_time -
                        build.start_time).total_seconds()
        else:
            duration = None

        ret = {
            'uuid': build.uuid,
            'job_name': build.job_name,
            'result': build.result,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'voting': build.voting,
            'log_url': build.log_url,
            'node_name': build.node_name,
            'artifacts': [],
            'provides': [],
        }

        if buildset:
            ret.update({
                'project': buildset.project,
                'branch': buildset.branch,
                'pipeline': buildset.pipeline,
                'change': buildset.change,
                'patchset': buildset.patchset,
                'ref': buildset.ref,
                'newrev': buildset.newrev,
                'ref_url': buildset.ref_url,
            })

        for artifact in build.artifacts:
            art = {
                'name': artifact.name,
                'url': artifact.url,
            }
            if artifact.meta:
                art['metadata'] = json.loads(artifact.meta)
            ret['artifacts'].append(art)
        for provides in build.provides:
            ret['provides'].append({
                'name': provides.name,
            })
        return ret

    def _get_connection(self, tenant):
        # Ask the scheduler which sql connection to use for this tenant
        job = self.rpc.submitJob('zuul:tenant_sql_connection',
                                 {'tenant': tenant})
        connection_name = json.loads(job.data[0])

        if not connection_name:
            raise cherrypy.HTTPError(404, 'Tenant %s does not exist.' % tenant)

        return self.zuulweb.connections.connections[connection_name]

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def builds(self, tenant, project=None, pipeline=None, change=None,
               branch=None, patchset=None, ref=None, newrev=None,
               uuid=None, job_name=None, voting=None, node_name=None,
               result=None, limit=50, skip=0):
        connection = self._get_connection(tenant)

        builds = connection.getBuilds(
            tenant=tenant, project=project, pipeline=pipeline, change=change,
            branch=branch, patchset=patchset, ref=ref, newrev=newrev,
            uuid=uuid, job_name=job_name, voting=voting, node_name=node_name,
            result=result, limit=limit, offset=skip)

        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return [self.buildToDict(b, b.buildset) for b in builds]

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def build(self, tenant, uuid):
        connection = self._get_connection(tenant)

        data = connection.getBuilds(tenant=tenant, uuid=uuid, limit=1)
        if not data:
            raise cherrypy.HTTPError(404, "Build not found")
        data = self.buildToDict(data[0], data[0].buildset)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return data

    def buildsetToDict(self, buildset, builds=[]):
        ret = {
            'uuid': buildset.uuid,
            'result': buildset.result,
            'message': buildset.message,
            'project': buildset.project,
            'branch': buildset.branch,
            'pipeline': buildset.pipeline,
            'change': buildset.change,
            'patchset': buildset.patchset,
            'ref': buildset.ref,
            'newrev': buildset.newrev,
            'ref_url': buildset.ref_url,
        }
        if builds:
            ret['builds'] = []
        for build in builds:
            ret['builds'].append(self.buildToDict(build))
        return ret

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def buildsets(self, tenant, project=None, pipeline=None, change=None,
                  branch=None, patchset=None, ref=None, newrev=None,
                  uuid=None, result=None, limit=50, skip=0):
        connection = self._get_connection(tenant)

        buildsets = connection.getBuildsets(
            tenant=tenant, project=project, pipeline=pipeline, change=change,
            branch=branch, patchset=patchset, ref=ref, newrev=newrev,
            uuid=uuid, result=result,
            limit=limit, offset=skip)

        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return [self.buildsetToDict(b) for b in buildsets]

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def buildset(self, tenant, uuid):
        connection = self._get_connection(tenant)

        data = connection.getBuildset(tenant, uuid)
        if not data:
            raise cherrypy.HTTPError(404, "Buildset not found")
        data = self.buildsetToDict(data, data.builds)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return data

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.websocket(handler_cls=LogStreamHandler)
    def console_stream(self, tenant):
        cherrypy.request.ws_handler.zuulweb = self.zuulweb

    @cherrypy.expose
    @cherrypy.tools.save_params()
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def project_freeze_jobs(self, tenant, pipeline, project, branch):
        job = self.rpc.submitJob(
            'zuul:project_freeze_jobs',
            {
                'tenant': tenant,
                'project': project,
                'pipeline': pipeline,
                'branch': branch
            }
        )
        ret = json.loads(job.data[0])
        if not ret:
            raise cherrypy.HTTPError(404)
        resp = cherrypy.response
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return ret


class StaticHandler(object):
    def __init__(self, root):
        self.root = root

    def default(self, path, **kwargs):
        # Try to handle static file first
        handled = cherrypy.lib.static.staticdir(
            section="",
            dir=self.root,
            index='index.html')
        if not path or not handled:
            # When not found, serve the index.html
            return cherrypy.lib.static.serve_file(
                path=os.path.join(self.root, "index.html"),
                content_type="text/html")
        else:
            return cherrypy.lib.static.serve_file(
                path=os.path.join(self.root, path))


class StreamManager(object):
    log = logging.getLogger("zuul.web")

    def __init__(self):
        self.streamers = {}
        self.poll = select.poll()
        self.bitmask = (select.POLLIN | select.POLLERR |
                        select.POLLHUP | select.POLLNVAL)
        self.wake_read, self.wake_write = os.pipe()
        self.poll.register(self.wake_read, self.bitmask)

    def start(self):
        self._stopped = False
        self.thread = threading.Thread(
            target=self.run,
            name='StreamManager')
        self.thread.start()

    def stop(self):
        self._stopped = True
        os.write(self.wake_write, b'\n')
        self.thread.join()

    def run(self):
        while True:
            for fd, event in self.poll.poll():
                if self._stopped:
                    return
                if fd == self.wake_read:
                    os.read(self.wake_read, 1024)
                    continue
                streamer = self.streamers.get(fd)
                if streamer:
                    try:
                        streamer.handle(event)
                    except Exception:
                        self.log.exception("Error in streamer:")
                        streamer.errorClose()
                        self.unregisterStreamer(streamer)
                else:
                    try:
                        self.poll.unregister(fd)
                    except KeyError:
                        pass

    def registerStreamer(self, streamer):
        self.log.debug("Registering streamer %s", streamer)
        self.streamers[streamer.finger_socket.fileno()] = streamer
        self.poll.register(streamer.finger_socket.fileno(), self.bitmask)
        os.write(self.wake_write, b'\n')

    def unregisterStreamer(self, streamer):
        self.log.debug("Unregistering streamer %s", streamer)
        try:
            self.poll.unregister(streamer.finger_socket)
        except KeyError:
            pass
        try:
            del self.streamers[streamer.finger_socket.fileno()]
        except KeyError:
            pass


class ZuulWeb(object):
    log = logging.getLogger("zuul.web.ZuulWeb")

    def __init__(self, listen_address, listen_port,
                 gear_server, gear_port,
                 ssl_key=None, ssl_cert=None, ssl_ca=None,
                 static_cache_expiry=3600,
                 connections=None,
                 info=None,
                 static_path=None,
                 zk_hosts=None):
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
        self.zk = zuul.zk.ZooKeeper()
        if zk_hosts:
            self.zk.connect(hosts=zk_hosts, read_only=True)
        self.connections = connections
        self.stream_manager = StreamManager()

        route_map = cherrypy.dispatch.RoutesDispatcher()
        api = ZuulWebAPI(self)
        route_map.connect('api', '/api',
                          controller=api, action='index')
        route_map.connect('api', '/api/info',
                          controller=api, action='info')
        route_map.connect('api', '/api/connections',
                          controller=api, action='connections')
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
        route_map.connect('api', '/api/tenant/{tenant}/job/{job_name}',
                          controller=api, action='job')
        route_map.connect('api', '/api/tenant/{tenant}/projects',
                          controller=api, action='projects')
        route_map.connect('api', '/api/tenant/{tenant}/project/{project:.*}',
                          controller=api, action='project')
        route_map.connect(
            'api',
            '/api/tenant/{tenant}/pipeline/{pipeline}'
            '/project/{project:.*}/branch/{branch:.*}/freeze-jobs',
            controller=api, action='project_freeze_jobs'
        )
        route_map.connect('api', '/api/tenant/{tenant}/pipelines',
                          controller=api, action='pipelines')
        route_map.connect('api', '/api/tenant/{tenant}/labels',
                          controller=api, action='labels')
        route_map.connect('api', '/api/tenant/{tenant}/nodes',
                          controller=api, action='nodes')
        route_map.connect('api', '/api/tenant/{tenant}/key/{project:.*}.pub',
                          controller=api, action='key')
        route_map.connect('api', '/api/tenant/{tenant}/'
                          'project-ssh-key/{project:.*}.pub',
                          controller=api, action='project_ssh_key')
        route_map.connect('api', '/api/tenant/{tenant}/console-stream',
                          controller=api, action='console_stream')
        route_map.connect('api', '/api/tenant/{tenant}/builds',
                          controller=api, action='builds')
        route_map.connect('api', '/api/tenant/{tenant}/build/{uuid}',
                          controller=api, action='build')
        route_map.connect('api', '/api/tenant/{tenant}/buildsets',
                          controller=api, action='buildsets')
        route_map.connect('api', '/api/tenant/{tenant}/buildset/{uuid}',
                          controller=api, action='buildset')
        route_map.connect('api', '/api/tenant/{tenant}/config-errors',
                          controller=api, action='config_errors')

        for connection in connections.connections.values():
            controller = connection.getWebController(self)
            if controller:
                cherrypy.tree.mount(
                    controller,
                    '/api/connection/%s' % connection.connection_name)

        # Add fallthrough routes at the end for the static html/js files
        route_map.connect(
            'root_static', '/{path:.*}',
            controller=StaticHandler(self.static_path),
            action='default')

        conf = {
            '/': {
                'request.dispatch': route_map
            }
        }
        cherrypy.config.update({
            'global': {
                'environment': 'production',
                'server.socket_host': listen_address,
                'server.socket_port': int(listen_port),
            },
        })

        cherrypy.tree.mount(api, '/', config=conf)

    @property
    def port(self):
        return cherrypy.server.bound_addr[1]

    def start(self):
        self.log.debug("ZuulWeb starting")
        self.stream_manager.start()
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
        self.stream_manager.stop()
        self.zk.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    import zuul.lib.connections
    connections = zuul.lib.connections.ConnectionRegistry()
    z = ZuulWeb(listen_address="127.0.0.1", listen_port=9000,
                gear_server="127.0.0.1", gear_port=4730,
                connections=connections)
    z.start()
    cherrypy.engine.block()
