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
import time
import voluptuous as v
import urllib.parse

from zuul.reporter import BaseReporter


class SQLReporter(BaseReporter):
    """Sends off reports to a database."""

    name = 'sql'
    log = logging.getLogger("zuul.SQLReporter")

    artifact = {
        'name': str,
        'url': str,
    }
    zuul_data = {
        'zuul': {
            'log_url': str,
            'artifacts': [artifact],
            v.Extra: object,
        }
    }
    artifact_schema = v.Schema(zuul_data)

    def validateArtifactSchema(self, data):
        try:
            self.artifact_schema(data)
        except Exception:
            return False
        return True

    def report(self, item):
        """Create an entry into a database."""

        if not self.connection.tables_established:
            self.log.warn("SQL reporter (%s) is disabled " % self)
            return

        with self.connection.getSession() as db:
            db_buildset = db.createBuildSet(
                tenant=item.pipeline.tenant.name,
                pipeline=item.pipeline.name,
                project=item.change.project.name,
                change=getattr(item.change, 'number', None),
                patchset=getattr(item.change, 'patchset', None),
                ref=getattr(item.change, 'ref', ''),
                oldrev=getattr(item.change, 'oldrev', ''),
                newrev=getattr(item.change, 'newrev', ''),
                branch=getattr(item.change, 'branch', ''),
                zuul_ref=item.current_build_set.ref,
                ref_url=item.change.url,
                result=item.current_build_set.result,
                message=self._formatItemReport(item, with_jobs=False),
            )
            for job in item.getJobs():
                build = item.current_build_set.getBuild(job.name)
                if not build:
                    # build hasn't begun. The sql reporter can only send back
                    # stats about builds. It doesn't understand how to store
                    # information about the change.
                    continue
                # Ensure end_time is defined
                if not build.end_time:
                    build.end_time = time.time()

                (result, url) = item.formatJobResult(job)
                start = end = None
                if build.start_time:
                    start = datetime.datetime.fromtimestamp(
                        build.start_time,
                        tz=datetime.timezone.utc)
                if build.end_time:
                    end = datetime.datetime.fromtimestamp(
                        build.end_time,
                        tz=datetime.timezone.utc)

                db_build = db_buildset.createBuild(
                    uuid=build.uuid,
                    job_name=build.job.name,
                    result=result,
                    start_time=start,
                    end_time=end,
                    voting=build.job.voting,
                    log_url=url,
                    node_name=build.node_name,
                )

                if self.validateArtifactSchema(build.result_data):
                    artifacts = build.result_data.get('zuul', {}).get(
                        'artifacts', [])
                    default_url = build.result_data.get('zuul', {}).get(
                        'log_url')
                    if default_url:
                        if default_url[-1] != '/':
                            default_url += '/'
                    for artifact in artifacts:
                        url = artifact['url']
                        if default_url:
                            # If the artifact url is relative, it will
                            # be combined with the log_url; if it is
                            # absolute, it will replace it.
                            try:
                                url = urllib.parse.urljoin(default_url, url)
                            except Exception:
                                self.log.debug("Error parsing URL:",
                                               exc_info=1)
                        db_build.createArtifact(
                            name=artifact['name'],
                            url=url,
                        )
                else:
                    self.log.debug("Result data did not pass artifact schema "
                                   "validation: %s", build.result_data)


def getSchema():
    sql_reporter = v.Schema(None)
    return sql_reporter
