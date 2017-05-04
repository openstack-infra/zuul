# Copyright 2015 Rackspace Australia
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

import datetime
import logging
import voluptuous as v

from zuul.reporter import BaseReporter


class SQLReporter(BaseReporter):
    """Sends off reports to a database."""

    name = 'sql'
    log = logging.getLogger("zuul.reporter.mysql.SQLReporter")

    def __init__(self, driver, connection, config={}):
        super(SQLReporter, self).__init__(
            driver, connection, config)
        # TODO(jeblair): document this is stored as NULL if unspecified
        self.result_score = config.get('score', None)

    def report(self, pipeline, item):
        """Create an entry into a database."""

        if not self.connection.tables_established:
            self.log.warn("SQL reporter (%s) is disabled " % self)
            return

        with self.connection.engine.begin() as conn:
            buildset_ins = self.connection.zuul_buildset_table.insert().values(
                zuul_ref=item.current_build_set.ref,
                pipeline=item.pipeline.name,
                project=item.change.project.name,
                change=item.change.number,
                patchset=item.change.patchset,
                ref=item.change.refspec,
                score=self.result_score,
                message=self._formatItemReport(
                    pipeline, item, with_jobs=False),
            )
            buildset_ins_result = conn.execute(buildset_ins)
            build_inserts = []

            for job in item.getJobs():
                build = item.current_build_set.getBuild(job.name)
                if not build:
                    # build hasn't began. The sql reporter can only send back
                    # stats about builds. It doesn't understand how to store
                    # information about the change.
                    continue

                (result, url) = item.formatJobResult(job)

                build_inserts.append({
                    'buildset_id': buildset_ins_result.inserted_primary_key,
                    'uuid': build.uuid,
                    'job_name': build.job.name,
                    'result': result,
                    'start_time': datetime.datetime.fromtimestamp(
                        build.start_time),
                    'end_time': datetime.datetime.fromtimestamp(
                        build.end_time),
                    'voting': build.job.voting,
                    'log_url': url,
                    'node_name': build.node_name,
                })
            conn.execute(self.connection.zuul_build_table.insert(),
                         build_inserts)


def getSchema():
    sql_reporter = v.Schema({
        'score': int,
    })
    return sql_reporter
