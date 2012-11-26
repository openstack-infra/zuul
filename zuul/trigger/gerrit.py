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

import logging
import threading
import time
import urllib2
from zuul.lib import gerrit
from zuul.model import TriggerEvent, Change


class GerritEventConnector(threading.Thread):
    """Move events from Gerrit to the scheduler."""

    log = logging.getLogger("zuul.GerritEventConnector")

    def __init__(self, gerrit, sched):
        super(GerritEventConnector, self).__init__()
        self.gerrit = gerrit
        self.sched = sched
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.gerrit.addEvent(None)

    def _handleEvent(self):
        data = self.gerrit.getEvent()
        if self._stopped:
            return
        event = TriggerEvent()
        event.type = data.get('type')
        change = data.get('change')
        if change:
            event.project_name = change.get('project')
            event.branch = change.get('branch')
            event.change_number = change.get('number')
            event.change_url = change.get('url')
            patchset = data.get('patchSet')
            if patchset:
                event.patch_number = patchset.get('number')
                event.refspec = patchset.get('ref')
            event.approvals = data.get('approvals', [])
            event.comment = data.get('comment')
        refupdate = data.get('refUpdate')
        if refupdate:
            event.project_name = refupdate.get('project')
            event.ref = refupdate.get('refName')
            event.oldrev = refupdate.get('oldRev')
            event.newrev = refupdate.get('newRev')
        self.sched.addEvent(event)
        self.gerrit.eventDone()

    def run(self):
        while True:
            if self._stopped:
                return
            try:
                self._handleEvent()
            except:
                self.log.exception("Exception moving Gerrit event:")


class Gerrit(object):
    log = logging.getLogger("zuul.Gerrit")
    replication_timeout = 60
    replication_retry_interval = 5

    def __init__(self, config, sched):
        self.sched = sched
        self.config = config
        self.server = config.get('gerrit', 'server')
        if config.has_option('gerrit', 'baseurl'):
            self.baseurl = config.get('gerrit', 'baseurl')
        else:
            self.baseurl = 'https://%s' % self.server
        user = config.get('gerrit', 'user')
        if config.has_option('gerrit', 'sshkey'):
            sshkey = config.get('gerrit', 'sshkey')
        else:
            sshkey = None
        if config.has_option('gerrit', 'port'):
            port = int(config.get('gerrit', 'port'))
        else:
            port = 29418
        self.gerrit = gerrit.Gerrit(self.server, user, port, sshkey)
        self.gerrit.startWatching()
        self.gerrit_connector = GerritEventConnector(
            self.gerrit, sched)
        self.gerrit_connector.start()

    def stop(self):
        self.gerrit_connector.stop()
        self.gerrit_connector.join()

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
        ref = 'refs/heads/' + change.branch
        change._ref_sha = self.getRefSha(change.project.name,
                                         ref)
        return self.gerrit.review(change.project.name, changeid,
                                  message, action)

    def _getInfoRefs(self, project):
        url = "%s/p/%s/info/refs?service=git-upload-pack" % (
            self.baseurl, project)
        try:
            data = urllib2.urlopen(url).read()
        except:
            self.log.error("Cannot get references from %s" % url)
            raise  # keeps urllib2 error informations
        ret = {}
        read_headers = False
        read_advertisement = False
        if data[4] != '#':
            raise Exception("Gerrit repository does not support "
                            "git-upload-pack")
        i = 0
        while i < len(data):
            if len(data) - i < 4:
                raise Exception("Invalid length in info/refs")
            plen = int(data[i:i + 4], 16)
            i += 4
            # It's the length of the packet, including the 4 bytes of the
            # length itself, unless it's null, in which case the length is
            # not included.
            if plen > 0:
                plen -= 4
            if len(data) - i < plen:
                raise Exception("Invalid data in info/refs")
            line = data[i:i + plen]
            i += plen
            if not read_headers:
                if plen == 0:
                    read_headers = True
                continue
            if not read_advertisement:
                read_advertisement = True
                continue
            if plen == 0:
                # The terminating null
                continue
            line = line.strip()
            revision, ref = line.split()
            ret[ref] = revision
        return ret

    def getRefSha(self, project, ref):
        refs = {}
        try:
            refs = self._getInfoRefs(project)
        except:
            self.log.exception("Exception looking for ref %s" %
                               ref)
        sha = refs.get(ref, '')
        return sha

    def waitForRefSha(self, project, ref, old_sha=''):
        # Wait for the ref to show up in the repo
        start = time.time()
        while time.time() - start < self.replication_timeout:
            sha = self.getRefSha(project.name, ref)
            if old_sha != sha:
                return True
            time.sleep(self.replication_retry_interval)
        return False

    def isMerged(self, change, head=None):
        self.log.debug("Checking if change %s is merged" % change)
        if not change.number:
            self.log.debug("Change has no number; considering it merged")
            # Good question.  It's probably ref-updated, which, ah,
            # means it's merged.
            return True

        data = self.gerrit.query(change.number)
        change._data = data
        change.is_merged = self._isMerged(change)
        if not head:
            return change.is_merged
        if not change.is_merged:
            return False

        ref = 'refs/heads/' + change.branch
        self.log.debug("Waiting for %s to appear in git repo" % (change))
        if self.waitForRefSha(change.project, ref, change._ref_sha):
            self.log.debug("Change %s is in the git repo" %
                           (change))
            return True
        self.log.debug("Change %s did not appear in the git repo" %
                       (change))
        return False

    def _isMerged(self, change):
        data = change._data
        if not data:
            return False
        status = data.get('status')
        if not status:
            return False
        self.log.debug("Change %s status: %s" % (change, status))
        if status == 'MERGED' or status == 'SUBMITTED':
            return True

    def canMerge(self, change, allow_needs):
        if not change.number:
            self.log.debug("Change has no number; considering it merged")
            # Good question.  It's probably ref-updated, which, ah,
            # means it's merged.
            return True
        data = change._data
        if not data:
            return False
        if not 'submitRecords' in data:
            return False
        try:
            for sr in data['submitRecords']:
                if sr['status'] == 'OK':
                    return True
                elif sr['status'] == 'NOT_READY':
                    for label in sr['labels']:
                        if label['status'] == 'OK':
                            continue
                        elif label['status'] in ['NEED', 'REJECT']:
                            # It may be our own rejection, so we ignore
                            if label['label'].lower() not in allow_needs:
                                return False
                            continue
                        else:
                            # IMPOSSIBLE
                            return False
                else:
                    # CLOSED, RULE_ERROR
                    return False
        except:
            self.log.exception("Exception determining whether change"
                               "%s can merge:" % change)
            return False
        return True

    def getChange(self, number, patchset, changes=None):
        self.log.info("Getting information for %s,%s" % (number, patchset))
        if changes is None:
            changes = {}
        data = self.gerrit.query(number)
        project = self.sched.projects[data['project']]
        change = Change(project)
        change._data = data

        change.number = number
        change.patchset = patchset
        change.project = project
        change.branch = data['branch']
        change.url = data['url']
        max_ps = 0
        for ps in data['patchSets']:
            if ps['number'] == patchset:
                change.refspec = ps['ref']
            if int(ps['number']) > int(max_ps):
                max_ps = ps['number']
        if max_ps == patchset:
            change.is_current_patchset = True
        else:
            change.is_current_patchset = False

        change.is_merged = self._isMerged(change)
        if change.is_merged:
            # This change is merged, so we don't need to look any further
            # for dependencies.
            return change

        key = '%s,%s' % (number, patchset)
        changes[key] = change

        def cachedGetChange(num, ps):
            key = '%s,%s' % (num, ps)
            if key in changes:
                return changes.get(key)
            c = self.getChange(num, ps, changes)
            return c

        if 'dependsOn' in data:
            parts = data['dependsOn'][0]['ref'].split('/')
            dep_num, dep_ps = parts[3], parts[4]
            dep = cachedGetChange(dep_num, dep_ps)
            if not dep.is_merged:
                change.needs_change = dep

        if 'neededBy' in data:
            for needed in data['neededBy']:
                parts = needed['ref'].split('/')
                dep_num, dep_ps = parts[3], parts[4]
                dep = cachedGetChange(dep_num, dep_ps)
                if not dep.is_merged and dep.is_current_patchset:
                    change.needed_by_changes.append(dep)

        return change

    def getGitUrl(self, project):
        server = self.config.get('gerrit', 'server')
        user = self.config.get('gerrit', 'user')
        if self.config.has_option('gerrit', 'port'):
            port = int(self.config.get('gerrit', 'port'))
        else:
            port = 29418
        url = 'ssh://%s@%s:%s/%s' % (user, server, port, project.name)
        return url
