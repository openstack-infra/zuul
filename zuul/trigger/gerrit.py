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
import re
import threading
import time
import urllib2
import voluptuous
from zuul.lib import gerrit
from zuul.model import TriggerEvent, Change, Ref, NullChange


class GerritEventConnector(threading.Thread):
    """Move events from Gerrit to the scheduler."""

    log = logging.getLogger("zuul.GerritEventConnector")

    def __init__(self, gerrit, sched, trigger):
        super(GerritEventConnector, self).__init__()
        self.daemon = True
        self.gerrit = gerrit
        self.sched = sched
        self.trigger = trigger
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
        event.trigger_name = self.trigger.name
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
        # Map the event types to a field name holding a Gerrit
        # account attribute. See Gerrit stream-event documentation
        # in cmd-stream-events.html
        accountfield_from_type = {
            'patchset-created': 'uploader',
            'draft-published': 'uploader',  # Gerrit 2.5/2.6
            'change-abandoned': 'abandoner',
            'change-restored': 'restorer',
            'change-merged': 'submitter',
            'merge-failed': 'submitter',  # Gerrit 2.5/2.6
            'comment-added': 'author',
            'ref-updated': 'submitter',
            'reviewer-added': 'reviewer',  # Gerrit 2.5/2.6
        }
        try:
            event.account = data.get(accountfield_from_type[event.type])
        except KeyError:
            self.log.error("Received unrecognized event type '%s' from Gerrit.\
                    Can not get account information." % event.type)
            event.account = None

        if event.change_number:
            # Call _getChange for the side effect of updating the
            # cache.  Note that this modifies Change objects outside
            # the main thread.
            self.trigger._getChange(event.change_number,
                                    event.patch_number,
                                    refresh=True)

        self.sched.addEvent(event)

    def run(self):
        while True:
            if self._stopped:
                return
            try:
                self._handleEvent()
            except:
                self.log.exception("Exception moving Gerrit event:")
            finally:
                self.gerrit.eventDone()


class Gerrit(object):
    name = 'gerrit'
    log = logging.getLogger("zuul.Gerrit")
    replication_timeout = 300
    replication_retry_interval = 5

    depends_on_re = re.compile(r"^Depends-On: (I[0-9a-f]{40})\s*$",
                               re.MULTILINE | re.IGNORECASE)

    def __init__(self, config, sched):
        self._change_cache = {}
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
            self.gerrit, sched, self)
        self.gerrit_connector.start()

    def stop(self):
        self.gerrit_connector.stop()
        self.gerrit_connector.join()

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
        if status == 'MERGED':
            return True
        return False

    def canMerge(self, change, allow_needs):
        if not change.number:
            self.log.debug("Change has no number; considering it merged")
            # Good question.  It's probably ref-updated, which, ah,
            # means it's merged.
            return True
        data = change._data
        if not data:
            return False
        if 'submitRecords' not in data:
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

    def maintainCache(self, relevant):
        # This lets the user supply a list of change objects that are
        # still in use.  Anything in our cache that isn't in the supplied
        # list should be safe to remove from the cache.
        remove = []
        for key, change in self._change_cache.items():
            if change not in relevant:
                remove.append(key)
        for key in remove:
            del self._change_cache[key]

    def postConfig(self):
        pass

    def getChange(self, event, project):
        if event.change_number:
            change = self._getChange(event.change_number, event.patch_number)
        elif event.ref:
            change = Ref(project)
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self.getGitwebUrl(project, sha=event.newrev)
        else:
            change = NullChange(project)
        return change

    def _getChange(self, number, patchset, refresh=False, history=None):
        key = '%s,%s' % (number, patchset)
        change = None
        if key in self._change_cache:
            change = self._change_cache.get(key)
            if not refresh:
                return change
        if not change:
            change = Change(None)
            change.number = number
            change.patchset = patchset
        key = '%s,%s' % (change.number, change.patchset)
        self._change_cache[key] = change
        try:
            self.updateChange(change, history)
        except Exception:
            del self._change_cache[key]
            raise
        return change

    def getProjectOpenChanges(self, project):
        # This is a best-effort function in case Gerrit is unable to return
        # a particular change.  It happens.
        query = "project:%s status:open" % (project.name,)
        self.log.debug("Running query %s to get project open changes" %
                       (query,))
        data = self.gerrit.simpleQuery(query)
        changes = []
        for record in data:
            try:
                changes.append(
                    self._getChange(record['number'],
                                    record['currentPatchSet']['number']))
            except Exception:
                self.log.exception("Unable to query change %s" %
                                   (record.get('number'),))
        return changes

    def _getDependsOnFromCommit(self, message):
        records = []
        seen = set()
        for match in self.depends_on_re.findall(message):
            if match in seen:
                self.log.debug("Ignoring duplicate Depends-On: %s" %
                               (match,))
                continue
            seen.add(match)
            query = "change:%s" % (match,)
            self.log.debug("Running query %s to find needed changes" %
                           (query,))
            records.extend(self.gerrit.simpleQuery(query))
        return records

    def updateChange(self, change, history=None):
        self.log.info("Updating information for %s,%s" %
                      (change.number, change.patchset))
        data = self.gerrit.query(change.number)
        change._data = data

        if change.patchset is None:
            change.patchset = data['currentPatchSet']['number']

        if 'project' not in data:
            raise Exception("Change %s,%s not found" % (change.number,
                                                        change.patchset))
        change.project = self.sched.getProject(data['project'])
        change.branch = data['branch']
        change.url = data['url']
        max_ps = 0
        change.files = []
        for ps in data['patchSets']:
            if ps['number'] == change.patchset:
                change.refspec = ps['ref']
                for f in ps.get('files', []):
                    change.files.append(f['file'])
            if int(ps['number']) > int(max_ps):
                max_ps = ps['number']
        if max_ps == change.patchset:
            change.is_current_patchset = True
        else:
            change.is_current_patchset = False

        change.is_merged = self._isMerged(change)
        change.approvals = data['currentPatchSet'].get('approvals', [])
        change.open = data['open']
        change.status = data['status']
        change.owner = data['owner']

        if change.is_merged:
            # This change is merged, so we don't need to look any further
            # for dependencies.
            return change

        if history is None:
            history = []
        else:
            history = history[:]
        history.append(change.number)

        change.needs_changes = []
        if 'dependsOn' in data:
            parts = data['dependsOn'][0]['ref'].split('/')
            dep_num, dep_ps = parts[3], parts[4]
            if dep_num in history:
                raise Exception("Dependency cycle detected: %s in %s" % (
                    dep_num, history))
            self.log.debug("Getting git-dependent change %s,%s" %
                           (dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            if (not dep.is_merged) and dep not in change.needs_changes:
                change.needs_changes.append(dep)

        for record in self._getDependsOnFromCommit(data['commitMessage']):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            if dep_num in history:
                raise Exception("Dependency cycle detected: %s in %s" % (
                    dep_num, history))
            self.log.debug("Getting commit-dependent change %s,%s" %
                           (dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            if (not dep.is_merged) and dep not in change.needs_changes:
                change.needs_changes.append(dep)

        change.needed_by_changes = []
        if 'neededBy' in data:
            for needed in data['neededBy']:
                parts = needed['ref'].split('/')
                dep_num, dep_ps = parts[3], parts[4]
                dep = self._getChange(dep_num, dep_ps)
                if (not dep.is_merged) and dep.is_current_patchset:
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

    def getGitwebUrl(self, project, sha=None):
        url = '%s/gitweb?p=%s.git' % (self.baseurl, project)
        if sha:
            url += ';a=commitdiff;h=' + sha
        return url


def validate_trigger(trigger_data):
    """Validates the layout's trigger data."""
    events_with_ref = ('ref-updated', )
    for event in trigger_data['gerrit']:
        if event['event'] not in events_with_ref and event.get('ref', False):
            raise voluptuous.Invalid(
                "The event %s does not include ref information, Zuul cannot "
                "use ref filter 'ref: %s'" % (event['event'], event['ref']))
