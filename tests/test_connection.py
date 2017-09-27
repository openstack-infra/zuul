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
import testtools

import sqlalchemy as sa

import zuul.connection.gerrit
import zuul.connection.sql

from tests.base import ZuulTestCase, ZuulDBTestCase


def _get_reporter_from_connection_name(reporters, connection_name):
    # Reporters are placed into lists for each action they may exist in.
    # Search through the given list for the correct reporter by its conncetion
    # name
    for r in reporters:
        if r.connection.connection_name == connection_name:
            return r


class TestGerritConnection(testtools.TestCase):
    log = logging.getLogger("zuul.test_connection")

    def test_driver_name(self):
        self.assertEqual('gerrit',
                         zuul.connection.gerrit.GerritConnection.driver_name)


class TestSQLConnection(testtools.TestCase):
    log = logging.getLogger("zuul.test_connection")

    def test_driver_name(self):
        self.assertEqual(
            'sql',
            zuul.connection.sql.SQLConnection.driver_name
        )


class TestConnections(ZuulDBTestCase):
    def test_multiple_gerrit_connections(self):
        "Test multiple connections to the one gerrit"

        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_review_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(A.patchsets[-1]['approvals']), 1)
        self.assertEqual(A.patchsets[-1]['approvals'][0]['type'], 'Verified')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['value'], '1')
        self.assertEqual(A.patchsets[-1]['approvals'][0]['by']['username'],
                         'jenkins')

        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.worker.addFailTest('project-test2', B)
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(len(B.patchsets[-1]['approvals']), 1)
        self.assertEqual(B.patchsets[-1]['approvals'][0]['type'], 'Verified')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['value'], '-1')
        self.assertEqual(B.patchsets[-1]['approvals'][0]['by']['username'],
                         'civoter')

    def _test_sql_tables_created(self, metadata_table=None):
        "Test the tables for storing results are created properly"
        buildset_table = 'zuul_buildset'
        build_table = 'zuul_build'

        insp = sa.engine.reflection.Inspector(
            self.connections['resultsdb'].engine)

        self.assertEqual(9, len(insp.get_columns(buildset_table)))
        self.assertEqual(10, len(insp.get_columns(build_table)))

    def test_sql_tables_created(self):
        "Test the default table is created"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-sql-reporter.yaml')
        self.sched.reconfigure(self.config)
        self._test_sql_tables_created()

    def _test_sql_results(self):
        "Test results are entered into an sql table"
        # Grab the sa tables
        reporter = _get_reporter_from_connection_name(
            self.sched.layout.pipelines['check'].success_actions,
            'resultsdb'
        )

        # Add a success result
        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_review_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Add a failed result for a negative score
        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.worker.addFailTest('project-test1', B)
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        conn = self.connections['resultsdb'].engine.connect()
        result = conn.execute(
            sa.sql.select([reporter.connection.zuul_buildset_table]))

        buildsets = result.fetchall()
        self.assertEqual(2, len(buildsets))
        buildset0 = buildsets[0]
        buildset1 = buildsets[1]

        self.assertEqual('check', buildset0['pipeline'])
        self.assertEqual('org/project', buildset0['project'])
        self.assertEqual(1, buildset0['change'])
        self.assertEqual(1, buildset0['patchset'])
        self.assertEqual(1, buildset0['score'])
        self.assertEqual('Build succeeded.', buildset0['message'])

        buildset0_builds = conn.execute(
            sa.sql.select([reporter.connection.zuul_build_table]).
            where(
                reporter.connection.zuul_build_table.c.buildset_id ==
                buildset0['id']
            )
        ).fetchall()

        # Check the first result, which should be the project-merge job
        self.assertEqual('project-merge', buildset0_builds[0]['job_name'])
        self.assertEqual("SUCCESS", buildset0_builds[0]['result'])
        self.assertEqual('http://logs.example.com/1/1/check/project-merge/0',
                         buildset0_builds[0]['log_url'])

        self.assertEqual('check', buildset1['pipeline'])
        self.assertEqual('org/project', buildset1['project'])
        self.assertEqual(2, buildset1['change'])
        self.assertEqual(1, buildset1['patchset'])
        self.assertEqual(-1, buildset1['score'])
        self.assertEqual('Build failed.', buildset1['message'])

        buildset1_builds = conn.execute(
            sa.sql.select([reporter.connection.zuul_build_table]).
            where(
                reporter.connection.zuul_build_table.c.buildset_id ==
                buildset1['id']
            )
        ).fetchall()

        # Check the second last result, which should be the project-test1 job
        # which failed
        self.assertEqual('project-test1', buildset1_builds[-2]['job_name'])
        self.assertEqual("FAILURE", buildset1_builds[-2]['result'])
        self.assertEqual('http://logs.example.com/2/1/check/project-test1/4',
                         buildset1_builds[-2]['log_url'])

    def test_sql_results(self):
        "Test results are entered into the default sql table"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-sql-reporter.yaml')
        self.sched.reconfigure(self.config)
        self._test_sql_results()

    def test_multiple_sql_connections(self):
        "Test putting results in different databases"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-sql-reporter.yaml')
        self.sched.reconfigure(self.config)

        # Add a successful result
        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_review_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Add a failed result
        B = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'B')
        self.worker.addFailTest('project-test1', B)
        self.fake_review_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        # Grab the sa tables for resultsdb
        reporter1 = _get_reporter_from_connection_name(
            self.sched.layout.pipelines['check'].success_actions,
            'resultsdb'
        )

        conn = self.connections['resultsdb'].engine.connect()
        buildsets_resultsdb = conn.execute(sa.sql.select(
            [reporter1.connection.zuul_buildset_table])).fetchall()
        # Should have been 2 buildset reported to the resultsdb (both success
        # and failure report)
        self.assertEqual(2, len(buildsets_resultsdb))

        # The first one should have passed
        self.assertEqual('check', buildsets_resultsdb[0]['pipeline'])
        self.assertEqual('org/project', buildsets_resultsdb[0]['project'])
        self.assertEqual(1, buildsets_resultsdb[0]['change'])
        self.assertEqual(1, buildsets_resultsdb[0]['patchset'])
        self.assertEqual(1, buildsets_resultsdb[0]['score'])
        self.assertEqual('Build succeeded.', buildsets_resultsdb[0]['message'])

        # Grab the sa tables for resultsdb_failures
        reporter2 = _get_reporter_from_connection_name(
            self.sched.layout.pipelines['check'].failure_actions,
            'resultsdb_failures'
        )

        conn = self.connections['resultsdb_failures'].engine.connect()
        buildsets_resultsdb_failures = conn.execute(sa.sql.select(
            [reporter2.connection.zuul_buildset_table])).fetchall()
        # The failure db should only have 1 buildset failed
        self.assertEqual(1, len(buildsets_resultsdb_failures))

        self.assertEqual('check', buildsets_resultsdb_failures[0]['pipeline'])
        self.assertEqual(
            'org/project', buildsets_resultsdb_failures[0]['project'])
        self.assertEqual(2, buildsets_resultsdb_failures[0]['change'])
        self.assertEqual(1, buildsets_resultsdb_failures[0]['patchset'])
        self.assertEqual(-1, buildsets_resultsdb_failures[0]['score'])
        self.assertEqual(
            'Build failed.', buildsets_resultsdb_failures[0]['message'])


class TestConnectionsBadSQL(ZuulDBTestCase):
    def setup_config(self, config_file='zuul-connections-bad-sql.conf'):
        super(TestConnectionsBadSQL, self).setup_config(config_file)

    def test_unable_to_connect(self):
        "Test the SQL reporter fails gracefully when unable to connect"
        self.config.set('zuul', 'layout_config',
                        'tests/fixtures/layout-sql-reporter.yaml')
        self.sched.reconfigure(self.config)

        # Trigger a reporter. If no errors are raised, the reporter has been
        # disabled correctly
        A = self.fake_review_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_review_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()


class TestMultipleGerrits(ZuulTestCase):
    def setup_config(self,
                     config_file='zuul-connections-multiple-gerrits.conf'):
        super(TestMultipleGerrits, self).setup_config(config_file)
        self.config.set(
            'zuul', 'layout_config',
            'layout-connections-multiple-gerrits.yaml')

    def test_multiple_project_separate_gerrits(self):
        self.worker.hold_jobs_in_build = True

        A = self.fake_another_gerrit.addFakeChange(
            'org/project', 'master', 'A')
        self.fake_another_gerrit.addEvent(A.getPatchsetCreatedEvent(1))

        self.waitUntilSettled()

        self.assertEqual(1, len(self.builds))
        self.assertEqual('project-another-gerrit', self.builds[0].name)
        self.assertTrue(self.job_has_changes(self.builds[0], A))

        self.worker.hold_jobs_in_build = False
        self.worker.release()
        self.waitUntilSettled()
