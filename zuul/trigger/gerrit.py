# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import threading
import logging
from zuul.lib import gerrit
from zuul.model import TriggerEvent


class GerritEventConnector(threading.Thread):
    """Move events from Gerrit to the scheduler."""

    log = logging.getLogger("zuul.GerritEventConnector")

    def __init__(self, gerrit, sched):
        super(GerritEventConnector, self).__init__()
        self.gerrit = gerrit
        self.sched = sched

    def _handleEvent(self):
        data = self.gerrit.getEvent()
        event = TriggerEvent()
        event.type = data.get('type')
        change = data.get('change')
        if change:
            event.project_name = change.get('project')
            event.branch = change.get('branch')
            event.change_number = change.get('number')
            patchset = data.get('patchSet')
            if patchset:
                event.patch_number = patchset.get('number')
                event.refspec = patchset.get('ref')
            event.approvals = data.get('approvals', [])
        refupdate = data.get('refUpdate')
        if refupdate:
            event.project_name = refupdate.get('project')
            event.ref = refupdate.get('refName')
            event.oldrev = refupdate.get('oldRev')
            event.newrev = refupdate.get('newRev')
        self.sched.addEvent(event)

    def run(self):
        while True:
            try:
                self._handleEvent()
            except:
                self.log.exception("Exception moving Gerrit event:")


class Gerrit(object):
    log = logging.getLogger("zuul.Gerrit")

    def __init__(self, config, sched):
        self.sched = sched
        server = config.get('gerrit', 'server')
        user = config.get('gerrit', 'user')
        if config.has_option('gerrit', 'sshkey'):
            sshkey = config.get('gerrit', 'sshkey')
        else:
            sshkey = None
        if config.has_option('gerrit', 'port'):
            port = config.get('gerrit', 'port')
        else:
            port = 29418
        self.gerrit = gerrit.Gerrit(server, user, port, sshkey)
        self.gerrit.startWatching()
        self.gerrit_connector = GerritEventConnector(
            self.gerrit, sched)
        self.gerrit_connector.start()

    def report(self, change, message, action):
        self.log.debug("Report change %s, action %s, message: %s" %
                       (change, action, message))
        if not change.number:
            self.log.debug("Change has no number; not reporting")
            return
        if not action:
            self.log.debug("No action specified; not reporting")
            return
        changeid = '%s,%s' % (change.number, change.patchset)
        return self.gerrit.review(change.project.name, changeid,
                                  message, action)

    def isMerged(self, change):
        self.log.debug("Checking if change %s is merged", change)
        if not change.number:
            self.log.debug("Change has no number; considering it merged")
            # Good question.  It's probably ref-updated, which, ah,
            # means it's merged.
            return True
        data = self.gerrit.query(change.number)
        if not data:
            return False
        status = data.get('status')
        if not status:
            return False
        self.log.debug("Change %s status: %s" % (change, status))
        if status == 'MERGED' or status == 'SUBMITTED':
            return True
