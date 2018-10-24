# Copyright 2013 Rackspace Australia
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

from zuul.driver.gerrit.gerritsource import GerritSource
from zuul.reporter import BaseReporter


class GerritReporter(BaseReporter):
    """Sends off reports to Gerrit."""

    name = 'gerrit'
    log = logging.getLogger("zuul.GerritReporter")

    def _getFileComments(self, item):
        ret = {}
        for build in item.current_build_set.getBuilds():
            fc = build.result_data.get('zuul', {}).get('file_comments')
            if not fc:
                continue
            for fn, comments in fc.items():
                existing_comments = ret.setdefault(fn, [])
                existing_comments += comments
        self.addConfigurationErrorComments(item, ret)
        return ret

    def report(self, item):
        """Send a message to gerrit."""

        # If the source is no GerritSource we cannot report anything here.
        if not isinstance(item.change.project.source, GerritSource):
            return

        # For supporting several Gerrit connections we also must filter by
        # the canonical hostname.
        if item.change.project.source.connection.canonical_hostname != \
                self.connection.canonical_hostname:
            return

        comments = self._getFileComments(item)
        self.filterComments(item, comments)
        message = self._formatItemReport(item)

        self.log.debug("Report change %s, params %s,"
                       " message: %s, comments: %s" %
                       (item.change, self.config, message, comments))
        item.change._ref_sha = item.change.project.source.getRefSha(
            item.change.project, 'refs/heads/' + item.change.branch)

        return self.connection.review(item.change, message, self.config,
                                      comments)

    def getSubmitAllowNeeds(self):
        """Get a list of code review labels that are allowed to be
        "needed" in the submit records for a change, with respect
        to this queue.  In other words, the list of review labels
        this reporter itself is likely to set before submitting.
        """
        return self.config


def getSchema():
    gerrit_reporter = v.Any(str, v.Schema(dict))
    return gerrit_reporter
