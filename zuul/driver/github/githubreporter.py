# Copyright 2015 Puppet Labs
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
import voluptuous as v

from zuul.reporter import BaseReporter


class GithubReporter(BaseReporter):
    """Sends off reports to Github."""

    name = 'github'
    log = logging.getLogger("zuul.GithubReporter")

    def report(self, source, pipeline, item):
        """Comment on PR with test status."""
        message = self._formatItemReport(pipeline, item)
        project = item.change.project.name
        pr_number = item.change.number

        self.connection.report(project, pr_number, message)


def getSchema():
    github_reporter = v.Any(str, v.Schema({}, extra=True))
    return github_reporter
