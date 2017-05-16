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
import time

from zuul.reporter import BaseReporter
from zuul.exceptions import MergeFailure


class GithubReporter(BaseReporter):
    """Sends off reports to Github."""

    name = 'github'
    log = logging.getLogger("zuul.GithubReporter")

    def __init__(self, driver, connection, config=None):
        super(GithubReporter, self).__init__(driver, connection, config)
        self._commit_status = self.config.get('status', None)
        self._create_comment = self.config.get('comment', True)
        self._merge = self.config.get('merge', False)
        self._labels = self.config.get('label', [])
        if not isinstance(self._labels, list):
            self._labels = [self._labels]
        self._unlabels = self.config.get('unlabel', [])
        if not isinstance(self._unlabels, list):
            self._unlabels = [self._unlabels]

    def report(self, source, pipeline, item):
        """Comment on PR and set commit status."""
        if self._create_comment:
            self.addPullComment(pipeline, item)
        if (self._commit_status is not None and
            hasattr(item.change, 'patchset') and
            item.change.patchset is not None):
            self.setPullStatus(pipeline, item)
        if (self._merge and
            hasattr(item.change, 'number')):
            self.mergePull(item)
        if self._labels or self._unlabels:
            self.setLabels(item)

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

    def mergePull(self, item):
        project = item.change.project.name
        pr_number = item.change.number
        sha = item.change.patchset
        self.log.debug('Reporting change %s, params %s, merging via API' %
                       (item.change, self.config))
        try:
            self.connection.mergePull(project, pr_number, sha)
        except MergeFailure:
            time.sleep(2)
            self.log.debug('Trying to merge change %s again...' % item.change)
            self.connection.mergePull(project, pr_number, sha)
        item.change.is_merged = True

    def setLabels(self, item):
        project = item.change.project.name
        pr_number = item.change.number
        if self._labels:
            self.log.debug('Reporting change %s, params %s, labels:\n%s' %
                           (item.change, self.config, self._labels))
        for label in self._labels:
                self.connection.labelPull(project, pr_number, label)
        if self._unlabels:
            self.log.debug('Reporting change %s, params %s, unlabels:\n%s' %
                           (item.change, self.config, self._unlabels))
        for label in self._unlabels:
                self.connection.unlabelPull(project, pr_number, label)


def getSchema():
    def toList(x):
        return v.Any([x], x)

    github_reporter = v.Schema({
        'status': v.Any('pending', 'success', 'failure'),
        'comment': bool,
        'merge': bool,
        'label': toList(str),
        'unlabel': toList(str)
    })
    return github_reporter
