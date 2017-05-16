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

    def __init__(self, driver, connection, config=None):
        super(GithubReporter, self).__init__(driver, connection, config)
        self._commit_status = self.config.get('status', None)
        self._create_comment = self.config.get('comment', True)

    def report(self, source, pipeline, item):
        """Comment on PR and set commit status."""
        if self._create_comment:
            self.addPullComment(pipeline, item)
        if (self._commit_status is not None and
            hasattr(item.change, 'patchset') and
            item.change.patchset is not None):
            self.setPullStatus(pipeline, item)

    def addPullComment(self, pipeline, item):
        message = self._formatItemReport(pipeline, item)
        project = item.change.project.name
        pr_number = item.change.number
        self.log.debug(
            'Reporting change %s, params %s, message: %s' %
            (item.change, self.config, message))
        self.connection.commentPull(project, pr_number, message)

    def setPullStatus(self, pipeline, item):
        project = item.change.project.name
        sha = item.change.patchset
        context = pipeline.name
        state = self._commit_status
        url = ''
        if self.connection.sched.config.has_option('zuul', 'status_url'):
            url = self.connection.sched.config.get('zuul', 'status_url')
        description = ''
        if pipeline.description:
            description = pipeline.description

        self.log.debug(
            'Reporting change %s, params %s, status:\n'
            'context: %s, state: %s, description: %s, url: %s' %
            (item.change, self.config, context, state,
             description, url))

        self.connection.setCommitStatus(
            project, sha, state, url, description, context)


def getSchema():
    github_reporter = v.Schema({
        'status': v.Any('pending', 'success', 'failure'),
        'comment': bool
    })
    return github_reporter
