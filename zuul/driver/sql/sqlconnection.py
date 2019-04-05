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
from sqlalchemy import orm
import sqlalchemy.pool

from zuul.connection import BaseConnection

BUILDSET_TABLE = 'zuul_buildset'
BUILD_TABLE = 'zuul_build'
ARTIFACT_TABLE = 'zuul_artifact'
PROVIDES_TABLE = 'zuul_provides'


class DatabaseSession(object):

    log = logging.getLogger("zuul.DatabaseSession")

    def __init__(self, connection):
        self.connection = connection
        self.session = connection.session

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if etype:
            self.session().rollback()
        else:
            self.session().commit()
        self.session().close()
        self.session = None

    def listFilter(self, query, column, value):
        if value is None:
            return query
        if isinstance(value, list) or isinstance(value, tuple):
            return query.filter(column.in_(value))
        return query.filter(column == value)

    def getBuilds(self, tenant=None, project=None, pipeline=None,
                  change=None, branch=None, patchset=None, ref=None,
                  newrev=None, uuid=None, job_name=None, voting=None,
                  node_name=None, result=None, provides=None,
                  limit=50, offset=0):

        build_table = self.connection.zuul_build_table
        buildset_table = self.connection.zuul_buildset_table
        provides_table = self.connection.zuul_provides_table

        # contains_eager allows us to perform eager loading on the
        # buildset *and* use that table in filters (unlike
        # joinedload).
        q = self.session().query(self.connection.buildModel).\
            join(self.connection.buildSetModel).\
            outerjoin(self.connection.providesModel).\
            options(orm.contains_eager(self.connection.buildModel.buildset),
                    orm.selectinload(self.connection.buildModel.provides),
                    orm.selectinload(self.connection.buildModel.artifacts)).\
            with_hint(build_table, 'USE INDEX (PRIMARY)', 'mysql')

        q = self.listFilter(q, buildset_table.c.tenant, tenant)
        q = self.listFilter(q, buildset_table.c.project, project)
        q = self.listFilter(q, buildset_table.c.pipeline, pipeline)
        q = self.listFilter(q, buildset_table.c.change, change)
        q = self.listFilter(q, buildset_table.c.branch, branch)
        q = self.listFilter(q, buildset_table.c.patchset, patchset)
        q = self.listFilter(q, buildset_table.c.ref, ref)
        q = self.listFilter(q, buildset_table.c.newrev, newrev)
        q = self.listFilter(q, build_table.c.uuid, uuid)
        q = self.listFilter(q, build_table.c.job_name, job_name)
        q = self.listFilter(q, build_table.c.voting, voting)
        q = self.listFilter(q, build_table.c.node_name, node_name)
        q = self.listFilter(q, build_table.c.result, result)
        q = self.listFilter(q, provides_table.c.name, provides)

        q = q.order_by(build_table.c.id.desc()).\
            limit(limit).\
            offset(offset)

        try:
            return q.all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def createBuildSet(self, *args, **kw):
        bs = self.connection.buildSetModel(*args, **kw)
        self.session().add(bs)
        self.session().flush()
        return bs

    def getBuildsets(self, tenant=None, project=None, pipeline=None,
                     change=None, branch=None, patchset=None, ref=None,
                     newrev=None, uuid=None, result=None,
                     limit=50, offset=0):

        buildset_table = self.connection.zuul_buildset_table

        q = self.session().query(self.connection.buildSetModel).\
            with_hint(buildset_table, 'USE INDEX (PRIMARY)', 'mysql')

        q = self.listFilter(q, buildset_table.c.tenant, tenant)
        q = self.listFilter(q, buildset_table.c.project, project)
        q = self.listFilter(q, buildset_table.c.pipeline, pipeline)
        q = self.listFilter(q, buildset_table.c.change, change)
        q = self.listFilter(q, buildset_table.c.branch, branch)
        q = self.listFilter(q, buildset_table.c.patchset, patchset)
        q = self.listFilter(q, buildset_table.c.ref, ref)
        q = self.listFilter(q, buildset_table.c.newrev, newrev)
        q = self.listFilter(q, buildset_table.c.uuid, uuid)
        q = self.listFilter(q, buildset_table.c.result, result)

        q = q.order_by(buildset_table.c.id.desc()).\
            limit(limit).\
            offset(offset)

        try:
            return q.all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getBuildset(self, tenant, uuid):
        """Get one buildset with its builds"""

        buildset_table = self.connection.zuul_buildset_table

        q = self.session().query(self.connection.buildSetModel).\
            options(orm.joinedload(self.connection.buildSetModel.builds).
                    subqueryload(self.connection.buildModel.artifacts)).\
            options(orm.joinedload(self.connection.buildSetModel.builds).
                    subqueryload(self.connection.buildModel.provides)).\
            with_hint(buildset_table, 'USE INDEX (PRIMARY)', 'mysql')

        q = self.listFilter(q, buildset_table.c.tenant, tenant)
        q = self.listFilter(q, buildset_table.c.uuid, uuid)

        try:
            return q.one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None
        except sqlalchemy.orm.exc.MultipleResultsFound:
            self.log.error("Multiple buildset found with uuid %s", uuid)
            return None


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
            self._setup_models()

            # Recycle connections if they've been idle for more than 1 second.
            # MySQL connections are lightweight and thus keeping long-lived
            # connections around is not valuable.
            self.engine = sa.create_engine(
                self.dburi,
                poolclass=sqlalchemy.pool.QueuePool,
                pool_recycle=self.connection_config.get('pool_recycle', 1))

            # If we want the objects returned from query() to be
            # usable outside of the session, we need to expunge them
            # from the session, and since the DatabaseSession always
            # calls commit() on the session when the context manager
            # exits, we need to inform the session not to expire
            # objects when it does so.
            self.session_factory = orm.sessionmaker(bind=self.engine,
                                                    expire_on_commit=False,
                                                    autoflush=False)
            self.session = orm.scoped_session(self.session_factory)

        except sa.exc.NoSuchModuleError:
            self.log.exception(
                "The required module for the dburi dialect isn't available. "
                "SQL connection %s will be unavailable." % connection_name)
        except sa.exc.OperationalError:
            self.log.exception(
                "Unable to connect to the database or establish the required "
                "tables. Reporter %s is disabled" % self)

    def getSession(self):
        return DatabaseSession(self)

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

    def onLoad(self):
        try:
            self._migrate()
            self.tables_established = True
        except sa.exc.NoSuchModuleError:
            self.log.exception(
                "The required module for the dburi dialect isn't available. "
                "SQL connection %s will be unavailable." %
                self.connection_name)
        except sa.exc.OperationalError:
            self.log.exception(
                "Unable to connect to the database or establish the required "
                "tables. Connection %s is disabled" % self)

    def _setup_models(self):
        Base = declarative_base(metadata=sa.MetaData())

        class BuildSetModel(Base):
            __tablename__ = self.table_prefix + BUILDSET_TABLE
            id = sa.Column(sa.Integer, primary_key=True)
            uuid = sa.Column(sa.String(36))
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

            def createBuild(self, *args, **kw):
                session = orm.session.Session.object_session(self)
                b = BuildModel(*args, **kw)
                b.buildset_id = self.id
                self.builds.append(b)
                session.add(b)
                session.flush()
                return b

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
            buildset = orm.relationship(BuildSetModel, backref="builds")

            def createArtifact(self, *args, **kw):
                session = orm.session.Session.object_session(self)
                # SQLAlchemy reserves the 'metadata' attribute on
                # object models, so our model and table names use
                # 'meta', but here we accept data directly from
                # zuul_return where it's called 'metadata'.  Transform
                # the attribute name.
                if 'metadata' in kw:
                    kw['meta'] = kw['metadata']
                    del kw['metadata']
                a = ArtifactModel(*args, **kw)
                a.build_id = self.id
                self.artifacts.append(a)
                session.add(a)
                session.flush()
                return a

            def createProvides(self, *args, **kw):
                session = orm.session.Session.object_session(self)
                p = ProvidesModel(*args, **kw)
                p.build_id = self.id
                self.provides.append(p)
                session.add(p)
                session.flush()
                return p

        class ArtifactModel(Base):
            __tablename__ = self.table_prefix + ARTIFACT_TABLE
            id = sa.Column(sa.Integer, primary_key=True)
            build_id = sa.Column(sa.Integer, sa.ForeignKey(
                self.table_prefix + BUILD_TABLE + ".id"))
            name = sa.Column(sa.String(255))
            url = sa.Column(sa.TEXT())
            meta = sa.Column('metadata', sa.TEXT())
            build = orm.relationship(BuildModel, backref="artifacts")

        class ProvidesModel(Base):
            __tablename__ = self.table_prefix + PROVIDES_TABLE
            id = sa.Column(sa.Integer, primary_key=True)
            build_id = sa.Column(sa.Integer, sa.ForeignKey(
                self.table_prefix + BUILD_TABLE + ".id"))
            name = sa.Column(sa.String(255))
            build = orm.relationship(BuildModel, backref="provides")

        self.providesModel = ProvidesModel
        self.zuul_provides_table = self.providesModel.__table__

        self.artifactModel = ArtifactModel
        self.zuul_artifact_table = self.artifactModel.__table__

        self.buildModel = BuildModel
        self.zuul_build_table = self.buildModel.__table__

        self.buildSetModel = BuildSetModel
        self.zuul_buildset_table = self.buildSetModel.__table__

    def onStop(self):
        self.log.debug("Stopping SQL connection %s" % self.connection_name)
        self.engine.dispose()

    def getBuilds(self, *args, **kw):
        """Return a list of Build objects"""
        with self.getSession() as db:
            return db.getBuilds(*args, **kw)

    def getBuildsets(self, *args, **kw):
        """Return a list of BuildSet objects"""
        with self.getSession() as db:
            return db.getBuildsets(*args, **kw)

    def getBuildset(self, *args, **kw):
        """Return a BuildSet objects"""
        with self.getSession() as db:
            return db.getBuildset(*args, **kw)
