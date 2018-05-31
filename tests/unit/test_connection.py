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

import textwrap

import sqlalchemy as sa

from tests.base import ZuulTestCase, ZuulDBTestCase


def _get_reporter_from_connection_name(reporters, connection_name):
    # Reporters are placed into lists for each action they may exist in.
    # Search through the given list for the correct reporter by its conncetion
    # name
    for r in reporters:
        if r.connection.connection_name == connection_name:
            return r


class TestConnections(ZuulTestCase):
    config_file = 'zuul-connections-same-gerrit.conf'
    tenant_config_file = 'config/zuul-connections-same-gerrit/main.yaml'

    def test_multiple_gerrit_connections(self):
        "Test multiple connections to the one gerrit"

        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.addEvent('review_gerrit', A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(A.patchsets[-1]['approvals']), 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['type'], 'Verified')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '1')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['by']['username'],
                         'jenkins')

        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.executor_server.failJob('project-test2', B)
        self.addEvent('review_gerrit', B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(B.patchsets[-1]['approvals']), 1)
        self.assertEqual(B.patchsets[-1]['approvals'][0]['type'], 'Verified')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['by']['username'],
                         'civoter')


class TestSQLConnection(ZuulDBTestCase):
    config_file = 'zuul-sql-driver.conf'
    tenant_config_file = 'config/sql-driver/main.yaml'
    expected_table_prefix = ''

    def _sql_tables_created(self, connection_name):
        connection = self.connections.connections[connection_name]
        insp = sa.engine.reflection.Inspector(connection.engine)

        table_prefix = connection.table_prefix
        self.assertEqual(self.expected_table_prefix, table_prefix)

        buildset_table = table_prefix + 'zuul_buildset'
        build_table = table_prefix + 'zuul_build'

        self.assertEqual(14, len(insp.get_columns(buildset_table)))
        self.assertEqual(10, len(insp.get_columns(build_table)))

    def test_sql_tables_created(self):
        "Test the tables for storing results are created properly"
        self._sql_tables_created('resultsdb_mysql')
        self._sql_tables_created('resultsdb_postgresql')

    def _sql_indexes_created(self, connection_name):
        connection = self.connections.connections[connection_name]
        insp = sa.engine.reflection.Inspector(connection.engine)

        table_prefix = connection.table_prefix
        self.assertEqual(self.expected_table_prefix, table_prefix)

        buildset_table = table_prefix + 'zuul_buildset'
        build_table = table_prefix + 'zuul_build'

        indexes_buildset = insp.get_indexes(buildset_table)
        indexes_build = insp.get_indexes(build_table)

        # Remove implicitly generated indexes by the foreign key.
        # MySQL creates an implicit index with the name if the column (which
        # is not a problem as in MySQL the index names are scoped within the
        # table). This is an implementation detail of the db engine so don't
        # check this.
        indexes_build = [x for x in indexes_build
                         if x['name'] != 'buildset_id']

        self.assertEqual(3, len(indexes_buildset))
        self.assertEqual(1, len(indexes_build))

        # check if all indexes are prefixed
        if table_prefix:
            indexes = indexes_buildset + indexes_build
            for index in indexes:
                self.assertTrue(index['name'].startswith(table_prefix))

    def test_sql_indexes_created(self):
        "Test the indexes are created properly"
        self._sql_indexes_created('resultsdb_mysql')
        self._sql_indexes_created('resultsdb_postgresql')

    def test_sql_results(self):
        "Test results are entered into an sql table"

        def check_results(connection_name):
            # Grab the sa tables
            tenant = self.sched.abide.tenants.get('tenant-one')
            reporter = _get_reporter_from_connection_name(
                tenant.layout.pipelines['check'].success_actions,
                connection_name
            )

            conn = self.connections.connections[
                connection_name].engine.connect()
            result = conn.execute(
                sa.sql.select([reporter.connection.zuul_buildset_table]))

            buildsets = result.fetchall()
            self.assertEqual(3, len(buildsets))
            buildset0 = buildsets[0]
            buildset1 = buildsets[1]
            buildset2 = buildsets[2]

            self.assertEqual('check', buildset0['pipeline'])
            self.assertEqual('org/project', buildset0['project'])
            self.assertEqual(1, buildset0['change'])
            self.assertEqual('1', buildset0['patchset'])
            self.assertEqual('SUCCESS', buildset0['result'])
            self.assertEqual('Build succeeded.', buildset0['message'])
            self.assertEqual('tenant-one', buildset0['tenant'])
            self.assertEqual(
                'https://review.example.com/%d' % buildset0['change'],
                buildset0['ref_url'])

            buildset0_builds = conn.execute(
                sa.sql.select([reporter.connection.zuul_build_table]).where(
                    reporter.connection.zuul_build_table.c.buildset_id ==
                    buildset0['id']
                )
            ).fetchall()

            # Check the first result, which should be the project-merge job
            self.assertEqual('project-merge', buildset0_builds[0]['job_name'])
            self.assertEqual("SUCCESS", buildset0_builds[0]['result'])
            self.assertEqual(
                'finger://{hostname}/{uuid}'.format(
                    hostname=self.executor_server.hostname,
                    uuid=buildset0_builds[0]['uuid']),
                buildset0_builds[0]['log_url'])
            self.assertEqual('check', buildset1['pipeline'])
            self.assertEqual('master', buildset1['branch'])
            self.assertEqual('org/project', buildset1['project'])
            self.assertEqual(2, buildset1['change'])
            self.assertEqual('1', buildset1['patchset'])
            self.assertEqual('FAILURE', buildset1['result'])
            self.assertEqual('Build failed.', buildset1['message'])

            buildset1_builds = conn.execute(
                sa.sql.select([reporter.connection.zuul_build_table]).where(
                    reporter.connection.zuul_build_table.c.buildset_id ==
                    buildset1['id']
                )
            ).fetchall()

            # Check the second result, which should be the project-test1 job
            # which failed
            self.assertEqual('project-test1', buildset1_builds[1]['job_name'])
            self.assertEqual("FAILURE", buildset1_builds[1]['result'])
            self.assertEqual(
                'finger://{hostname}/{uuid}'.format(
                    hostname=self.executor_server.hostname,
                    uuid=buildset1_builds[1]['uuid']),
                buildset1_builds[1]['log_url'])

            buildset2_builds = conn.execute(
                sa.sql.select([reporter.connection.zuul_build_table]).where(
                    reporter.connection.zuul_build_table.c.buildset_id ==
                    buildset2['id']
                )
            ).fetchall()

            # Check the first result, which should be the project-publish job
            self.assertEqual('project-publish',
                             buildset2_builds[0]['job_name'])
            self.assertEqual("SUCCESS", buildset2_builds[0]['result'])

        self.executor_server.hold_jobs_in_build = True

        # Add a success result
        self.log.debug("Adding success FakeChange")
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.orderedRelease()
        self.waitUntilSettled()

        # Add a failed result
        self.log.debug("Adding failed FakeChange")
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')

        self.executor_server.failJob('project-test1', B)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()
        self.orderedRelease()
        self.waitUntilSettled()

        # Add a tag result
        self.log.debug("Adding FakeTag event")
        C = self.fake_gerrit.addFakeTag('org/project', 'master', 'foo')
        self.fake_gerrit.addEvent(C)
        self.waitUntilSettled()
        self.orderedRelease()
        self.waitUntilSettled()

        check_results('resultsdb_mysql')
        check_results('resultsdb_postgresql')

    def test_multiple_sql_connections(self):
        "Test putting results in different databases"
        # Add a successful result
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Add a failed result
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B')
        self.executor_server.failJob('project-test1', B)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        def check_results(connection_name_1, connection_name_2):
            # Grab the sa tables for resultsdb
            tenant = self.sched.abide.tenants.get('tenant-one')
            reporter1 = _get_reporter_from_connection_name(
                tenant.layout.pipelines['check'].success_actions,
                connection_name_1
            )

            conn = self.connections.connections[connection_name_1].\
                engine.connect()
            buildsets_resultsdb = conn.execute(sa.sql.select(
                [reporter1.connection.zuul_buildset_table])).fetchall()
            # Should have been 2 buildset reported to the resultsdb (both
            # success and failure report)
            self.assertEqual(2, len(buildsets_resultsdb))

            # The first one should have passed
            self.assertEqual('check', buildsets_resultsdb[0]['pipeline'])
            self.assertEqual(
                'org/project', buildsets_resultsdb[0]['project'])
            self.assertEqual(1, buildsets_resultsdb[0]['change'])
            self.assertEqual('1', buildsets_resultsdb[0]['patchset'])
            self.assertEqual('SUCCESS', buildsets_resultsdb[0]['result'])
            self.assertEqual(
                'Build succeeded.', buildsets_resultsdb[0]['message'])

            # Grab the sa tables for resultsdb_mysql_failures
            reporter2 = _get_reporter_from_connection_name(
                tenant.layout.pipelines['check'].failure_actions,
                connection_name_2
            )

            conn = self.connections.connections[connection_name_2].\
                engine.connect()
            buildsets_resultsdb_failures = conn.execute(sa.sql.select(
                [reporter2.connection.zuul_buildset_table])).fetchall()
            # The failure db should only have 1 buildset failed
            self.assertEqual(1, len(buildsets_resultsdb_failures))

            self.assertEqual(
                'check', buildsets_resultsdb_failures[0]['pipeline'])
            self.assertEqual('org/project',
                             buildsets_resultsdb_failures[0]['project'])
            self.assertEqual(2,
                             buildsets_resultsdb_failures[0]['change'])
            self.assertEqual(
                '1', buildsets_resultsdb_failures[0]['patchset'])
            self.assertEqual(
                'FAILURE', buildsets_resultsdb_failures[0]['result'])
            self.assertEqual('Build failed.',
                             buildsets_resultsdb_failures[0]['message'])

        check_results('resultsdb_mysql', 'resultsdb_mysql_failures')
        check_results('resultsdb_postgresql', 'resultsdb_postgresql_failures')


class TestSQLConnectionPrefix(TestSQLConnection):
    config_file = 'zuul-sql-driver-prefix.conf'
    expected_table_prefix = 'prefix_'


class TestConnectionsBadSQL(ZuulDBTestCase):
    config_file = 'zuul-sql-driver-bad.conf'
    tenant_config_file = 'config/sql-driver/main.yaml'

    def test_unable_to_connect(self):
        "Test the SQL reporter fails gracefully when unable to connect"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-sql-reporter.yaml')
        self.sched.reconfigure(self.config)

        # Trigger a reporter. If no errors are raised, the reporter has been
        # disabled correctly
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()


class TestMultipleGerrits(ZuulTestCase):
    config_file = 'zuul-connections-multiple-gerrits.conf'
    tenant_config_file = 'config/zuul-connections-multiple-gerrits/main.yaml'

    def test_multiple_project_separate_gerrits(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_another_gerrit.addFakeChange(
            'org/project1', 'master', 'A')
        self.fake_another_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([dict(name='project-test2',
                                changes='1,1',
                                project='org/project1',
                                pipeline='another_check')])

        # NOTE(jamielennox): the tests back the git repo for both connections
        # onto the same git repo on the file system. If we just create another
        # fake change the fake_review_gerrit will try to create another 1,1
        # change and git will fail to create the ref. Arbitrarily set it to get
        # around the problem.
        self.fake_review_gerrit.change_number = 50

        B = self.fake_review_gerrit.addFakeChange(
            'org/project1', 'master', 'B')
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='project-test2',
                 changes='1,1',
                 project='org/project1',
                 pipeline='another_check'),
            dict(name='project-test1',
                 changes='51,1',
                 project='org/project1',
                 pipeline='review_check'),
        ])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

    def test_multiple_project_separate_gerrits_common_pipeline(self):
        self.executor_server.hold_jobs_in_build = True

        A = self.fake_another_gerrit.addFakeChange(
            'org/project2', 'master', 'A')
        self.fake_another_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([dict(name='project-test2',
                                changes='1,1',
                                project='org/project2',
                                pipeline='common_check')])

        # NOTE(jamielennox): the tests back the git repo for both connections
        # onto the same git repo on the file system. If we just create another
        # fake change the fake_review_gerrit will try to create another 1,1
        # change and git will fail to create the ref. Arbitrarily set it to get
        # around the problem.
        self.fake_review_gerrit.change_number = 50

        B = self.fake_review_gerrit.addFakeChange(
            'org/project2', 'master', 'B')
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertBuilds([
            dict(name='project-test2',
                 changes='1,1',
                 project='org/project2',
                 pipeline='common_check'),
            dict(name='project-test1',
                 changes='51,1',
                 project='org/project2',
                 pipeline='common_check'),
        ])

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()


class TestConnectionsMerger(ZuulTestCase):
    config_file = 'zuul-connections-merger.conf'
    tenant_config_file = 'config/single-tenant/main.yaml'

    def configure_connections(self):
        super(TestConnectionsMerger, self).configure_connections(True)

    def test_connections_merger(self):
        "Test merger only configures source connections"

        self.assertIn("gerrit", self.connections.connections)
        self.assertIn("github", self.connections.connections)
        self.assertNotIn("smtp", self.connections.connections)
        self.assertNotIn("sql", self.connections.connections)
        self.assertNotIn("timer", self.connections.connections)
        self.assertNotIn("zuul", self.connections.connections)


class TestConnectionsCgit(ZuulTestCase):
    config_file = 'zuul-connections-cgit.conf'
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_cgit_web_url(self):
        self.assertIn("gerrit", self.connections.connections)
        conn = self.connections.connections['gerrit']
        source = conn.source
        proj = source.getProject('foo/bar')
        url = conn._getWebUrl(proj, '1')
        self.assertEqual(url,
                         'https://cgit.example.com/cgit/foo/bar/commit/?id=1')


class TestConnectionsGitweb(ZuulTestCase):
    config_file = 'zuul-connections-gitweb.conf'
    tenant_config_file = 'config/single-tenant/main.yaml'

    def test_gitweb_url(self):
        self.assertIn("gerrit", self.connections.connections)
        conn = self.connections.connections['gerrit']
        source = conn.source
        proj = source.getProject('foo/bar')
        url = conn._getWebUrl(proj, '1')
        url_should_be = 'https://review.example.com/' \
                        'gitweb?p=foo/bar.git;a=commitdiff;h=1'
        self.assertEqual(url, url_should_be)


class TestMQTTConnection(ZuulTestCase):
    config_file = 'zuul-mqtt-driver.conf'
    tenant_config_file = 'config/mqtt-driver/main.yaml'

    def test_mqtt_reporter(self):
        "Test the MQTT reporter"
        # Add a success result
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        success_event = self.mqtt_messages.pop()
        start_event = self.mqtt_messages.pop()

        self.assertEquals(start_event.get('topic'),
                          'tenant-one/zuul_start/check/org/project/master')
        mqtt_payload = start_event['msg']
        self.assertEquals(mqtt_payload['project'], 'org/project')
        self.assertEquals(mqtt_payload['branch'], 'master')
        self.assertEquals(mqtt_payload['buildset']['builds'][0]['job_name'],
                          'test')
        self.assertNotIn('result', mqtt_payload['buildset']['builds'][0])

        self.assertEquals(success_event.get('topic'),
                          'tenant-one/zuul_buildset/check/org/project/master')
        mqtt_payload = success_event['msg']
        self.assertEquals(mqtt_payload['project'], 'org/project')
        self.assertEquals(mqtt_payload['branch'], 'master')
        self.assertEquals(mqtt_payload['buildset']['builds'][0]['job_name'],
                          'test')
        self.assertEquals(mqtt_payload['buildset']['builds'][0]['result'],
                          'SUCCESS')

    def test_mqtt_invalid_topic(self):
        in_repo_conf = textwrap.dedent(
            """
            - pipeline:
                name: test-pipeline
                manager: independent
                trigger:
                  gerrit:
                    - event: comment-added
                start:
                  mqtt:
                    topic: "{bad}/{topic}"
            """)
        file_dict = {'zuul.d/test.yaml': in_repo_conf}
        A = self.fake_gerrit.addFakeChange('common-config', 'master', 'A',
                                           files=file_dict)
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        self.assertIn("topic component 'bad' is invalid", A.messages[0],
                      "A should report a syntax error")
