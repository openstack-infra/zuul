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
import sqlalchemy.pool
import voluptuous as v

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


def getSchema():
    sql_connection = v.Any(str, v.Schema(dict))
    return sql_connection
