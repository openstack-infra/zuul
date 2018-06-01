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

import logging
from aiohttp import web
import urllib.parse

from zuul.driver import Driver, ConnectionInterface, ReporterInterface
from zuul.driver.sql import sqlconnection
from zuul.driver.sql import sqlreporter


class SQLDriver(Driver, ConnectionInterface, ReporterInterface):
    name = 'sql'
    log = logging.getLogger("zuul.SQLDriver")

    def __init__(self):
        self.tenant_connections = {}

    def reconfigure(self, tenant):
        # NOTE(corvus): This stores the connection of the first
        # reporter seen for each tenant; we should figure out how to
        # support multiple connections for a tenant (how do we deal
        # with pagination of queries across multiple connections), or
        # otherwise, require there only be one connection in a tenant.
        if tenant.name in self.tenant_connections:
            del self.tenant_connections[tenant.name]
        for pipeline in tenant.layout.pipelines.values():
            reporters = (pipeline.start_actions + pipeline.success_actions
                         + pipeline.failure_actions
                         + pipeline.merge_failure_actions)
            for reporter in reporters:
                if not isinstance(reporter, sqlreporter.SQLReporter):
                    continue
                self.tenant_connections[tenant.name] = reporter.connection
                return

    def registerScheduler(self, scheduler):
        self.sched = scheduler

    def getConnection(self, name, config):
        return sqlconnection.SQLConnection(self, name, config)

    def getReporter(self, connection, config=None):
        return sqlreporter.SQLReporter(self, connection, config)

    def getReporterSchema(self):
        return sqlreporter.getSchema()

    # TODO(corvus): these are temporary, remove after cherrypy conversion
    def setEventLoop(self, event_loop):
        self.event_loop = event_loop

    async def handleRequest(self, request):
        tenant_name = request.match_info["tenant"]
        connection = self.tenant_connections.get(tenant_name)
        if not connection:
            return
        try:
            args = {
                'buildset_filters': {},
                'build_filters': {},
                'limit': 50,
                'skip': 0,
                'tenant': tenant_name,
            }
            for k, v in urllib.parse.parse_qsl(request.rel_url.query_string):
                if k in ("project", "pipeline", "change", "branch",
                         "patchset", "ref", "newrev"):
                    args['buildset_filters'].setdefault(k, []).append(v)
                elif k in ("uuid", "job_name", "voting", "node_name",
                           "result"):
                    args['build_filters'].setdefault(k, []).append(v)
                elif k in ("limit", "skip"):
                    args[k] = int(v)
                else:
                    raise ValueError("Unknown parameter %s" % k)
            data = await connection.get_builds(args, self.event_loop)
            resp = web.json_response(data)
            resp.headers['Access-Control-Allow-Origin'] = '*'
        except Exception as e:
            self.log.exception("Jobs exception:")
            resp = web.json_response({'error_description': 'Internal error'},
                                     status=500)
        return resp
