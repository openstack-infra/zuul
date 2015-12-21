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

import six


@six.add_metaclass(abc.ABCMeta)
class BaseReporter(object):
    """Base class for reporters.

    Defines the exact public methods that must be supplied.
    """

    log = logging.getLogger("zuul.reporter.BaseReporter")

    def __init__(self, reporter_config={}, sched=None, connection=None):
        self.reporter_config = reporter_config
        self.sched = sched
        self.connection = connection
        self._action = None

    def setAction(self, action):
        self._action = action

    def stop(self):
        """Stop the reporter."""

    @abc.abstractmethod
    def report(self, source, pipeline, item):
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

    def _formatItemReport(self, pipeline, item):
        """Format a report from the given items. Usually to provide results to
        a reporter taking free-form text."""
        ret = self._getFormatter()(pipeline, item)

        if pipeline.footer_message:
            ret += '\n' + pipeline.footer_message

        return ret

    def _formatItemReportStart(self, pipeline, item):
        msg = "Starting %s jobs." % pipeline.name
        if self.sched.config.has_option('zuul', 'status_url'):
            msg += "\n" + self.sched.config.get('zuul', 'status_url')
        return msg

    def _formatItemReportSuccess(self, pipeline, item):
        return (pipeline.success_message + '\n\n' +
                self._formatItemReportJobs(pipeline, item))

    def _formatItemReportFailure(self, pipeline, item):
        if item.dequeued_needing_change:
            msg = 'This change depends on a change that failed to merge.\n'
        elif not pipeline.didMergerSucceed(item):
            msg = pipeline.merge_failure_message
        else:
            msg = (pipeline.failure_message + '\n\n' +
                   self._formatItemReportJobs(pipeline, item))
        return msg

    def _formatItemReportMergeFailure(self, pipeline, item):
        return pipeline.merge_failure_message

    def _formatItemReportDisabled(self, pipeline, item):
        if item.current_build_set.result == 'SUCCESS':
            return self._formatItemReportSuccess(pipeline, item)
        elif item.current_build_set.result == 'FAILURE':
            return self._formatItemReportFailure(pipeline, item)
        else:
            return self._formatItemReport(pipeline, item)

    def _formatItemReportJobs(self, pipeline, item):
        # Return the list of jobs portion of the report
        ret = ''

        if self.sched.config.has_option('zuul', 'url_pattern'):
            url_pattern = self.sched.config.get('zuul', 'url_pattern')
        else:
            url_pattern = None

        for job in pipeline.getJobs(item):
            build = item.current_build_set.getBuild(job.name)
            (result, url) = item.formatJobResult(job, url_pattern)
            if not job.voting:
                voting = ' (non-voting)'
            else:
                voting = ''

            if self.sched.config and self.sched.config.has_option(
                'zuul', 'report_times'):
                report_times = self.sched.config.getboolean(
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
            name = ''
            if self.sched.config.has_option('zuul', 'job_name_in_report'):
                if self.sched.config.getboolean('zuul',
                                                'job_name_in_report'):
                    name = job.name + ' '
            ret += '- %s%s : %s%s%s\n' % (name, url, result, elapsed,
                                          voting)
        return ret
