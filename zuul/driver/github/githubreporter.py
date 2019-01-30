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
from zuul.driver.util import scalar_or_list
from zuul.driver.github.githubsource import GithubSource


class GithubReporter(BaseReporter):
    """Sends off reports to Github."""

    name = 'github'
    log = logging.getLogger("zuul.GithubReporter")

    def __init__(self, driver, connection, pipeline, config=None):
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
        self.context = "{}/{}".format(pipeline.tenant.name, pipeline.name)

    def report(self, item):
        """Report on an event."""

        # If the source is not GithubSource we cannot report anything here.
        if not isinstance(item.change.project.source, GithubSource):
            return

        # For supporting several Github connections we also must filter by
        # the canonical hostname.
        if item.change.project.source.connection.canonical_hostname != \
                self.connection.canonical_hostname:
            return

        # order is important for github branch protection.
        # A status should be set before a merge attempt
        if self._commit_status is not None:
            if (hasattr(item.change, 'patchset') and
                    item.change.patchset is not None):
                self.setCommitStatus(item)
            elif (hasattr(item.change, 'newrev') and
                    item.change.newrev is not None):
                self.setCommitStatus(item)
        # Comments, labels, and merges can only be performed on pull requests.
        # If the change is not a pull request (e.g. a push) skip them.
        if hasattr(item.change, 'number'):
            if self._create_comment:
                self.addPullComment(item)
            if self._labels or self._unlabels:
                self.setLabels(item)
            if (self._merge):
                self.mergePull(item)
                if not item.change.is_merged:
                    msg = self._formatItemReportMergeFailure(item)
                    self.addPullComment(item, msg)

    def _formatItemReportJobs(self, item):
        # Return the list of jobs portion of the report
        ret = ''
        jobs_fields = self._getItemReportJobsFields(item)
        for job_fields in jobs_fields:
            ret += '- [%s](%s) : %s%s%s%s\n' % job_fields
        return ret

    def addPullComment(self, item, comment=None):
        message = comment or self._formatItemReport(item)
        project = item.change.project.name
        pr_number = item.change.number
        self.log.debug(
            'Reporting change %s, params %s, message: %s' %
            (item.change, self.config, message))
        self.connection.commentPull(project, pr_number, message)

    def setCommitStatus(self, item):
        project = item.change.project.name
        if hasattr(item.change, 'patchset'):
            sha = item.change.patchset
        elif hasattr(item.change, 'newrev'):
            sha = item.change.newrev
        state = self._commit_status

        url_pattern = self.config.get('status-url')
        if not url_pattern:
            sched_config = self.connection.sched.config
            if sched_config.has_option('web', 'status_url'):
                url_pattern = sched_config.get('web', 'status_url')
        url = item.formatUrlPattern(url_pattern) if url_pattern else ''

        description = '%s status: %s' % (item.pipeline.name,
                                         self._commit_status)

        if len(description) >= 140:
            # This pipeline is named with a long name and thus this
            # desciption would overflow the GitHub limit of 1024 bytes.
            # Truncate the description. In practice, anything over 140
            # characters seems to trip the limit.
            description = 'status: %s' % self._commit_status

        self.log.debug(
            'Reporting change %s, params %s, '
            'context: %s, state: %s, description: %s, url: %s' %
            (item.change, self.config,
             self.context, state, description, url))

        self.connection.setCommitStatus(
            project, sha, state, url, description, self.context)

    def mergePull(self, item):
        project = item.change.project.name
        pr_number = item.change.number
        sha = item.change.patchset
        self.log.debug('Reporting change %s, params %s, merging via API' %
                       (item.change, self.config))
        message = self._formatMergeMessage(item.change)

        for i in [1, 2]:
            try:
                self.connection.mergePull(project, pr_number, message, sha)
                item.change.is_merged = True
                return
            except MergeFailure:
                self.log.exception(
                    'Merge attempt of change %s  %s/2 failed.' %
                    (item.change, i), exc_info=True)
                if i == 1:
                    time.sleep(2)
        self.log.warning(
            'Merge of change %s failed after 2 attempts, giving up' %
            item.change)

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

    def _formatMergeMessage(self, change):
        message = ''

        if change.title:
            message += change.title

        account = getattr(change.source_event, 'account', None)
        if not account:
            return message

        username = account['username']
        name = account['name']
        email = account['email']
        message += '\n\nReviewed-by: '

        if name:
            message += name
        if email:
            if name:
                message += ' '
            message += '<' + email + '>'
        if name or email:
            message += '\n             '
        message += self.connection.getUserUri(username)

        return message

    def getSubmitAllowNeeds(self):
        """Get a list of code review labels that are allowed to be
        "needed" in the submit records for a change, with respect
        to this queue.  In other words, the list of review labels
        this reporter itself is likely to set before submitting.
        """

        # check if we report a status, if not we can return an empty list
        status = self.config.get('status')
        if not status:
            return []

        # we return a status so return the status we report to github
        return [self.context]


def getSchema():
    github_reporter = v.Schema({
        'status': v.Any('pending', 'success', 'failure'),
        'status-url': str,
        'comment': bool,
        'merge': bool,
        'label': scalar_or_list(str),
        'unlabel': scalar_or_list(str)
    })
    return github_reporter
