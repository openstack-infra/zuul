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

import logging

import alembic
import alembic.command
import alembic.config
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import sqlalchemy.pool
from sqlalchemy.sql import select
import voluptuous

from zuul.connection import BaseConnection

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
                = self._setup_models()
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

    def _setup_models(self):
        Base = declarative_base(metadata=sa.MetaData())

        class BuildModel(Base):
            __tablename__ = self.table_prefix + BUILD_TABLE
            id = sa.Column(sa.Integer, primary_key=True)
            buildset_id = sa.Column(sa.String, sa.ForeignKey(
                self.table_prefix + BUILDSET_TABLE + ".id"))
            uuid = sa.Column(sa.String(36))
            job_name = sa.Column(sa.String(255))
            result = sa.Column(sa.String(255))
            start_time = sa.Column(sa.DateTime)
            end_time = sa.Column(sa.DateTime)
            voting = sa.Column(sa.Boolean)
            log_url = sa.Column(sa.String(255))
            node_name = sa.Column(sa.String(255))

        class BuildSetModel(Base):
            __tablename__ = self.table_prefix + BUILDSET_TABLE
            id = sa.Column(sa.Integer, primary_key=True)
            builds = relationship(BuildModel, lazy="subquery")
            zuul_ref = sa.Column(sa.String(255))
            pipeline = sa.Column(sa.String(255))
            project = sa.Column(sa.String(255))
            branch = sa.Column(sa.String(255))
            change = sa.Column(sa.Integer, nullable=True)
            patchset = sa.Column(sa.String(255), nullable=True)
            ref = sa.Column(sa.String(255))
            oldrev = sa.Column(sa.String(255))
            newrev = sa.Column(sa.String(255))
            ref_url = sa.Column(sa.String(255))
            result = sa.Column(sa.String(255))
            message = sa.Column(sa.TEXT())
            tenant = sa.Column(sa.String(255))

        self.buildModel = BuildModel
        self.buildSetModel = BuildSetModel
        return self.buildSetModel.__table__, self.buildModel.__table__

    def onStop(self):
        self.log.debug("Stopping SQL connection %s" % self.connection_name)
        self.engine.dispose()

    def query(self, args):
        build = self.zuul_build_table
        buildset = self.zuul_buildset_table
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

    def get_builds(self, args):
        """Return a list of build"""
        builds = []
        with self.engine.begin() as conn:
            for row in conn.execute(self.query(args)):
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


def getSchema():
    sql_connection = voluptuous.Any(str, voluptuous.Schema(dict))
    return sql_connection
