# Copyright 2014 Rackspace Australia
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

import asyncio
import logging

from aiohttp import web
import alembic
import alembic.command
import alembic.config
import sqlalchemy as sa
import sqlalchemy.pool
from sqlalchemy.sql import select
import urllib.parse
import voluptuous

from zuul.connection import BaseConnection
from zuul.lib.config import get_default
from zuul.web.handler import BaseTenantWebHandler

BUILDSET_TABLE = 'zuul_buildset'
BUILD_TABLE = 'zuul_build'


class SQLConnection(BaseConnection):
    driver_name = 'sql'
    log = logging.getLogger("zuul.SQLConnection")

    def __init__(self, driver, connection_name, connection_config):

        super(SQLConnection, self).__init__(driver, connection_name,
                                            connection_config)

        self.dburi = None
        self.engine = None
        self.connection = None
        self.tables_established = False
        self.table_prefix = self.connection_config.get('table_prefix', '')

        try:
            self.dburi = self.connection_config.get('dburi')
            # Recycle connections if they've been idle for more than 1 second.
            # MySQL connections are lightweight and thus keeping long-lived
            # connections around is not valuable.
            self.engine = sa.create_engine(
                self.dburi,
                poolclass=sqlalchemy.pool.QueuePool,
                pool_recycle=self.connection_config.get('pool_recycle', 1))
            self._migrate()
            self.zuul_buildset_table, self.zuul_build_table \
                = self._setup_tables()
            self.tables_established = True
        except sa.exc.NoSuchModuleError:
            self.log.exception(
                "The required module for the dburi dialect isn't available. "
                "SQL connection %s will be unavailable." % connection_name)
        except sa.exc.OperationalError:
            self.log.exception(
                "Unable to connect to the database or establish the required "
                "tables. Reporter %s is disabled" % self)

    def _migrate(self):
        """Perform the alembic migrations for this connection"""
        with self.engine.begin() as conn:
            context = alembic.migration.MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
            self.log.debug('Current migration revision: %s' % current_rev)

            config = alembic.config.Config()
            config.set_main_option("script_location",
                                   "zuul:driver/sql/alembic")
            config.set_main_option("sqlalchemy.url",
                                   self.connection_config.get('dburi'))

            # Alembic lets us add arbitrary data in the tag argument. We can
            # leverage that to tell the upgrade scripts about the table prefix.
            tag = {'table_prefix': self.table_prefix}
            alembic.command.upgrade(config, 'head', tag=tag)

    def _setup_tables(self):
        metadata = sa.MetaData()

        zuul_buildset_table = sa.Table(
            self.table_prefix + BUILDSET_TABLE, metadata,
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('zuul_ref', sa.String(255)),
            sa.Column('pipeline', sa.String(255)),
            sa.Column('project', sa.String(255)),
            sa.Column('branch', sa.String(255)),
            sa.Column('change', sa.Integer, nullable=True),
            sa.Column('patchset', sa.String(255), nullable=True),
            sa.Column('ref', sa.String(255)),
            sa.Column('oldrev', sa.String(255)),
            sa.Column('newrev', sa.String(255)),
            sa.Column('ref_url', sa.String(255)),
            sa.Column('result', sa.String(255)),
            sa.Column('message', sa.TEXT()),
            sa.Column('tenant', sa.String(255)),
        )

        zuul_build_table = sa.Table(
            self.table_prefix + BUILD_TABLE, metadata,
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('buildset_id', sa.Integer,
                      sa.ForeignKey(self.table_prefix +
                                    BUILDSET_TABLE + ".id")),
            sa.Column('uuid', sa.String(36)),
            sa.Column('job_name', sa.String(255)),
            sa.Column('result', sa.String(255)),
            sa.Column('start_time', sa.DateTime()),
            sa.Column('end_time', sa.DateTime()),
            sa.Column('voting', sa.Boolean),
            sa.Column('log_url', sa.String(255)),
            sa.Column('node_name', sa.String(255)),
        )

        return zuul_buildset_table, zuul_build_table

    def getWebHandlers(self, zuul_web, info):
        info.capabilities.job_history = True
        return [
            SqlWebHandler(self, zuul_web, 'GET', 'builds'),
        ]

    def validateWebConfig(self, config, connections):
        sql_conn_name = get_default(config, 'web', 'sql_connection_name')
        if sql_conn_name:
            # The config wants a specific sql connection. Check the whole
            # list of connections to make sure it can be satisfied.
            sql_conn = connections.connections.get(sql_conn_name)
            if not sql_conn:
                raise Exception(
                    "Couldn't find sql connection '%s'" % sql_conn_name)
            if self.connection_name == sql_conn.connection_name:
                return True
        else:
            # Check to see if there is more than one connection
            conn_objects = [c for c in connections.connections.values()
                            if isinstance(c, SQLConnection)]
            if len(conn_objects) > 1:
                raise Exception("Multiple sql connection found, "
                                "set the sql_connection_name option "
                                "in zuul.conf [web] section")
            return True

    def onStop(self):
        self.log.debug("Stopping SQL connection %s" % self.connection_name)
        self.engine.dispose()


class SqlWebHandler(BaseTenantWebHandler):
    log = logging.getLogger("zuul.web.SqlHandler")
    filters = ("project", "pipeline", "change", "branch", "patchset", "ref",
               "result", "uuid", "job_name", "voting", "node_name", "newrev")

    def __init__(self, connection, zuul_web, method, path):
        super(SqlWebHandler, self).__init__(
            connection=connection, zuul_web=zuul_web, method=method, path=path)

    def setEventLoop(self, event_loop):
        self.event_loop = event_loop

    def query(self, args):
        build = self.connection.zuul_build_table
        buildset = self.connection.zuul_buildset_table
        query = select([
            buildset.c.project,
            buildset.c.branch,
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
            for key, val in args['%s_filters' % table].items():
                if table == 'build':
                    column = build.c
                else:
                    column = buildset.c
                query = query.where(getattr(column, key).in_(val))
        return query.limit(args['limit']).offset(args['skip']).order_by(
            build.c.id.desc())

    async def get_builds(self, args):
        """Return a list of build"""
        builds = []
        with self.connection.engine.begin() as conn:
            query = self.query(args)
            query_task = self.event_loop.run_in_executor(
                None,
                conn.execute,
                query
            )
            rows = await asyncio.wait_for(query_task, 30)

            for row in rows:
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

    async def handleRequest(self, request):
        try:
            args = {
                'buildset_filters': {},
                'build_filters': {},
                'limit': 50,
                'skip': 0,
            }
            for k, v in urllib.parse.parse_qsl(request.rel_url.query_string):
                if k in ("tenant", "project", "pipeline", "change", "branch",
                         "patchset", "ref", "newrev"):
                    args['buildset_filters'].setdefault(k, []).append(v)
                elif k in ("uuid", "job_name", "voting", "node_name",
                           "result"):
                    args['build_filters'].setdefault(k, []).append(v)
                elif k in ("limit", "skip"):
                    args[k] = int(v)
                else:
                    raise ValueError("Unknown parameter %s" % k)
            data = await self.get_builds(args)
            resp = web.json_response(data)
            resp.headers['Access-Control-Allow-Origin'] = '*'
        except Exception as e:
            self.log.exception("Jobs exception:")
            resp = web.json_response({'error_description': 'Internal error'},
                                     status=500)
        return resp


def getSchema():
    sql_connection = voluptuous.Any(str, voluptuous.Schema(dict))
    return sql_connection
