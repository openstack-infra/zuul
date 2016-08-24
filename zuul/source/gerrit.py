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
import time
from zuul import exceptions
from zuul.model import Change, Ref, NullChange
from zuul.source import BaseSource


# Walk the change dependency tree to find a cycle
def detect_cycle(change, history=None):
    if history is None:
        history = []
    else:
        history = history[:]
    history.append(change.number)
    for dep in change.needs_changes:
        if dep.number in history:
            raise Exception("Dependency cycle detected: %s in %s" % (
                dep.number, history))
        detect_cycle(dep, history)


class GerritSource(BaseSource):
    name = 'gerrit'
    log = logging.getLogger("zuul.source.Gerrit")
    replication_timeout = 300
    replication_retry_interval = 5

    depends_on_re = re.compile(r"^Depends-On: (I[0-9a-f]{40})\s*$",
                               re.MULTILINE | re.IGNORECASE)

    def getRefSha(self, project, ref):
        refs = {}
        try:
            refs = self.connection.getInfoRefs(project)
        except:
            self.log.exception("Exception looking for ref %s" %
                               ref)
        sha = refs.get(ref, '')
        return sha

    def _waitForRefSha(self, project, ref, old_sha=''):
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

        data = self.connection.query(change.number)
        change._data = data
        change.is_merged = self._isMerged(change)
        if change.is_merged:
            self.log.debug("Change %s is merged" % (change,))
        else:
            self.log.debug("Change %s is not merged" % (change,))
        if not head:
            return change.is_merged
        if not change.is_merged:
            return False

        ref = 'refs/heads/' + change.branch
        self.log.debug("Waiting for %s to appear in git repo" % (change))
        if self._waitForRefSha(change.project, ref, change._ref_sha):
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
                        if label['status'] in ['OK', 'MAY']:
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

    def postConfig(self):
        pass

    def getChange(self, event, project):
        if event.change_number:
            refresh = False
            change = self._getChange(event.change_number, event.patch_number,
                                     refresh=refresh)
        elif event.ref:
            change = Ref(project)
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getGitwebUrl(project, sha=event.newrev)
        else:
            change = NullChange(project)
        return change

    def _getChange(self, number, patchset, refresh=False, history=None):
        key = '%s,%s' % (number, patchset)
        change = self.connection.getCachedChange(key)
        if change and not refresh:
            return change
        if not change:
            change = Change(None)
            change.number = number
            change.patchset = patchset
        key = '%s,%s' % (change.number, change.patchset)
        self.connection.updateChangeCache(key, change)
        try:
            self._updateChange(change, history)
        except Exception:
            self.connection.deleteCachedChange(key)
            raise
        return change

    def getProjectOpenChanges(self, project):
        # This is a best-effort function in case Gerrit is unable to return
        # a particular change.  It happens.
        query = "project:%s status:open" % (project.name,)
        self.log.debug("Running query %s to get project open changes" %
                       (query,))
        data = self.connection.simpleQuery(query)
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

    def _getDependsOnFromCommit(self, message, change):
        records = []
        seen = set()
        for match in self.depends_on_re.findall(message):
            if match in seen:
                self.log.debug("Ignoring duplicate Depends-On: %s" %
                               (match,))
                continue
            seen.add(match)
            query = "change:%s" % (match,)
            self.log.debug("Updating %s: Running query %s "
                           "to find needed changes" %
                           (change, query,))
            records.extend(self.connection.simpleQuery(query))
        return records

    def _getNeededByFromCommit(self, change_id, change):
        records = []
        seen = set()
        query = 'message:%s' % change_id
        self.log.debug("Updating %s: Running query %s "
                       "to find changes needed-by" %
                       (change, query,))
        results = self.connection.simpleQuery(query)
        for result in results:
            for match in self.depends_on_re.findall(
                result['commitMessage']):
                if match != change_id:
                    continue
                key = (result['number'], result['currentPatchSet']['number'])
                if key in seen:
                    continue
                self.log.debug("Updating %s: Found change %s,%s "
                               "needs %s from commit" %
                               (change, key[0], key[1], change_id))
                seen.add(key)
                records.append(result)
        return records

    def _updateChange(self, change, history=None):
        self.log.info("Updating %s" % (change,))
        data = self.connection.query(change.number)
        change._data = data

        if change.patchset is None:
            change.patchset = data['currentPatchSet']['number']

        if 'project' not in data:
            raise exceptions.ChangeNotFound(change.number, change.patchset)
        change.project = self.sched.getProject(data['project'])
        change.branch = data['branch']
        change.url = data['url']
        max_ps = 0
        files = []
        for ps in data['patchSets']:
            if ps['number'] == change.patchset:
                change.refspec = ps['ref']
                for f in ps.get('files', []):
                    files.append(f['file'])
            if int(ps['number']) > int(max_ps):
                max_ps = ps['number']
        if max_ps == change.patchset:
            change.is_current_patchset = True
        else:
            change.is_current_patchset = False
        change.files = files

        change.is_merged = self._isMerged(change)
        change.approvals = data['currentPatchSet'].get('approvals', [])
        change.open = data['open']
        change.status = data['status']
        change.owner = data['owner']

        if change.is_merged:
            # This change is merged, so we don't need to look any further
            # for dependencies.
            self.log.debug("Updating %s: change is merged" % (change,))
            return change

        if history is None:
            history = []
        else:
            history = history[:]
        history.append(change.number)

        needs_changes = []
        if 'dependsOn' in data:
            parts = data['dependsOn'][0]['ref'].split('/')
            dep_num, dep_ps = parts[3], parts[4]
            if dep_num in history:
                raise Exception("Dependency cycle detected: %s in %s" % (
                    dep_num, history))
            self.log.debug("Updating %s: Getting git-dependent change %s,%s" %
                           (change, dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            # Because we are not forcing a refresh in _getChange, it
            # may return without executing this code, so if we are
            # updating our change to add ourselves to a dependency
            # cycle, we won't detect it.  By explicitly performing a
            # walk of the dependency tree, we will.
            detect_cycle(dep, history)
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)

        for record in self._getDependsOnFromCommit(data['commitMessage'],
                                                   change):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            if dep_num in history:
                raise Exception("Dependency cycle detected: %s in %s" % (
                    dep_num, history))
            self.log.debug("Updating %s: Getting commit-dependent "
                           "change %s,%s" %
                           (change, dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            # Because we are not forcing a refresh in _getChange, it
            # may return without executing this code, so if we are
            # updating our change to add ourselves to a dependency
            # cycle, we won't detect it.  By explicitly performing a
            # walk of the dependency tree, we will.
            detect_cycle(dep, history)
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)
        change.needs_changes = needs_changes

        needed_by_changes = []
        if 'neededBy' in data:
            for needed in data['neededBy']:
                parts = needed['ref'].split('/')
                dep_num, dep_ps = parts[3], parts[4]
                self.log.debug("Updating %s: Getting git-needed change %s,%s" %
                               (change, dep_num, dep_ps))
                dep = self._getChange(dep_num, dep_ps)
                if (not dep.is_merged) and dep.is_current_patchset:
                    needed_by_changes.append(dep)

        for record in self._getNeededByFromCommit(data['id'], change):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            self.log.debug("Updating %s: Getting commit-needed change %s,%s" %
                           (change, dep_num, dep_ps))
            # Because a commit needed-by may be a cross-repo
            # dependency, cause that change to refresh so that it will
            # reference the latest patchset of its Depends-On (this
            # change).
            dep = self._getChange(dep_num, dep_ps, refresh=True)
            if (not dep.is_merged) and dep.is_current_patchset:
                needed_by_changes.append(dep)
        change.needed_by_changes = needed_by_changes

        return change

    def getGitUrl(self, project):
        return self.connection.getGitUrl(project)

    def _getGitwebUrl(self, project, sha=None):
        return self.connection.getGitwebUrl(project, sha)
