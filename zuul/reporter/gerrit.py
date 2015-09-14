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


from zuul.reporter import BaseReporter


class GerritReporter(BaseReporter):
    """Sends off reports to Gerrit."""

    name = 'gerrit'
    log = logging.getLogger("zuul.reporter.gerrit.Reporter")

    def report(self, source, pipeline, item):
        """Send a message to gerrit."""
        message = self._formatItemReport(pipeline, item)

        self.log.debug("Report change %s, params %s, message: %s" %
                       (item.change, self.reporter_config, message))
        changeid = '%s,%s' % (item.change.number, item.change.patchset)
        item.change._ref_sha = source.getRefSha(
            item.change.project.name, 'refs/heads/' + item.change.branch)

        return self.connection.review(item.change.project.name, changeid,
                                      message, self.reporter_config)

    def getSubmitAllowNeeds(self):
        """Get a list of code review labels that are allowed to be
        "needed" in the submit records for a change, with respect
        to this queue.  In other words, the list of review labels
        this reporter itself is likely to set before submitting.
        """
        return self.reporter_config


def getSchema():
    gerrit_reporter = v.Any(str, v.Schema({}, extra=True))
    return gerrit_reporter
