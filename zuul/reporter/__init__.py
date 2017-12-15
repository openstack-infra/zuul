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

import abc
import logging
from zuul.lib.config import get_default


class BaseReporter(object, metaclass=abc.ABCMeta):
    """Base class for reporters.

    Defines the exact public methods that must be supplied.
    """

    log = logging.getLogger("zuul.reporter.BaseReporter")

    def __init__(self, driver, connection, config=None):
        self.driver = driver
        self.connection = connection
        self.config = config or {}
        self._action = None

    def setAction(self, action):
        self._action = action

    @abc.abstractmethod
    def report(self, item):
        """Send the compiled report message."""

    def getSubmitAllowNeeds(self):
        """Get a list of code review labels that are allowed to be
        "needed" in the submit records for a change, with respect
        to this queue.  In other words, the list of review labels
        this reporter itself is likely to set before submitting.
        """
        return []

    def postConfig(self):
        """Run tasks after configuration is reloaded"""

    def _getFormatter(self):
        format_methods = {
            'start': self._formatItemReportStart,
            'success': self._formatItemReportSuccess,
            'failure': self._formatItemReportFailure,
            'merge-failure': self._formatItemReportMergeFailure,
            'disabled': self._formatItemReportDisabled
        }
        return format_methods[self._action]

    def _formatItemReport(self, item, with_jobs=True):
        """Format a report from the given items. Usually to provide results to
        a reporter taking free-form text."""
        ret = self._getFormatter()(item, with_jobs)

        if item.current_build_set.debug_messages:
            debug = '\n  '.join(item.current_build_set.debug_messages)
            ret += '\nDebug information:\n  ' + debug + '\n'

        if item.pipeline.footer_message:
            ret += '\n' + item.pipeline.footer_message

        return ret

    def _formatItemReportStart(self, item, with_jobs=True):
        status_url = get_default(self.connection.sched.config,
                                 'webapp', 'status_url', '')
        return item.pipeline.start_message.format(pipeline=item.pipeline,
                                                  status_url=status_url)

    def _formatItemReportSuccess(self, item, with_jobs=True):
        msg = item.pipeline.success_message
        if with_jobs:
            msg += '\n\n' + self._formatItemReportJobs(item)
        return msg

    def _formatItemReportFailure(self, item, with_jobs=True):
        if item.dequeued_needing_change:
            msg = 'This change depends on a change that failed to merge.\n'
        elif item.didMergerFail():
            msg = item.pipeline.merge_failure_message
        elif item.getConfigError():
            msg = item.getConfigError()
        else:
            msg = item.pipeline.failure_message
            if with_jobs:
                msg += '\n\n' + self._formatItemReportJobs(item)
        return msg

    def _formatItemReportMergeFailure(self, item, with_jobs=True):
        return item.pipeline.merge_failure_message

    def _formatItemReportDisabled(self, item, with_jobs=True):
        if item.current_build_set.result == 'SUCCESS':
            return self._formatItemReportSuccess(item)
        elif item.current_build_set.result == 'FAILURE':
            return self._formatItemReportFailure(item)
        else:
            return self._formatItemReport(item)

    def _formatItemReportJobs(self, item):
        # Return the list of jobs portion of the report
        ret = ''

        config = self.connection.sched.config

        for job in item.getJobs():
            build = item.current_build_set.getBuild(job.name)
            (result, url) = item.formatJobResult(job)
            if not job.voting:
                voting = ' (non-voting)'
            else:
                voting = ''

            if config and config.has_option(
                'zuul', 'report_times'):
                report_times = config.getboolean(
                    'zuul', 'report_times')
            else:
                report_times = True

            if report_times and build.end_time and build.start_time:
                dt = int(build.end_time - build.start_time)
                m, s = divmod(dt, 60)
                h, m = divmod(m, 60)
                if h:
                    elapsed = ' in %dh %02dm %02ds' % (h, m, s)
                elif m:
                    elapsed = ' in %dm %02ds' % (m, s)
                else:
                    elapsed = ' in %ds' % (s)
            else:
                elapsed = ''
            if build.error_detail:
                error = ' ' + build.error_detail
            else:
                error = ''
            name = job.name + ' '
            ret += '- %s%s : %s%s%s%s\n' % (name, url, result, error,
                                            elapsed, voting)
        return ret
