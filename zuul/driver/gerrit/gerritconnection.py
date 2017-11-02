# Copyright 2011 OpenStack, LLC.
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

import json
import re
import select
import threading
import time
import paramiko
import logging
import pprint
import shlex
import queue
import voluptuous as v

from typing import Dict, List

from zuul.connection import BaseConnection
from zuul.model import Ref, Tag, Branch, Project
from zuul import exceptions
from zuul.driver.gerrit.gerritmodel import GerritChange, GerritTriggerEvent


class GerritEventConnector(threading.Thread):
    """Move events from Gerrit to the scheduler."""

    log = logging.getLogger("zuul.GerritEventConnector")
    delay = 10.0

    def __init__(self, connection):
        super(GerritEventConnector, self).__init__()
        self.daemon = True
        self.connection = connection
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.connection.addEvent(None)

    def _handleEvent(self):
        ts, data = self.connection.getEvent()
        if self._stopped:
            return
        # Gerrit can produce inconsistent data immediately after an
        # event, So ensure that we do not deliver the event to Zuul
        # until at least a certain amount of time has passed.  Note
        # that if we receive several events in succession, we will
        # only need to delay for the first event.  In essence, Zuul
        # should always be a constant number of seconds behind Gerrit.
        now = time.time()
        time.sleep(max((ts + self.delay) - now, 0.0))
        event = GerritTriggerEvent()
        event.type = data.get('type')
        # This catches when a change is merged, as it could potentially
        # have merged layout info which will need to be read in.
        # Ideally this would be done with a refupdate event so as to catch
        # directly pushed things as well as full changes being merged.
        # But we do not yet get files changed data for pure refupdate events.
        # TODO(jlk): handle refupdated events instead of just changes
        if event.type == 'change-merged':
            event.branch_updated = True
        event.trigger_name = 'gerrit'
        change = data.get('change')
        event.project_hostname = self.connection.canonical_hostname
        if change:
            event.project_name = change.get('project')
            event.branch = change.get('branch')
            event.change_number = str(change.get('number'))
            event.change_url = change.get('url')
            patchset = data.get('patchSet')
            if patchset:
                event.patch_number = patchset.get('number')
                event.ref = patchset.get('ref')
            event.approvals = data.get('approvals', [])
            event.comment = data.get('comment')
        refupdate = data.get('refUpdate')
        if refupdate:
            event.project_name = refupdate.get('project')
            event.ref = refupdate.get('refName')
            event.oldrev = refupdate.get('oldRev')
            event.newrev = refupdate.get('newRev')
        if event.project_name is None:
            # ref-replica* events
            event.project_name = data.get('project')
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
            'ref-replicated': None,
            'ref-replication-done': None,
            'ref-replication-scheduled': None,
            'topic-changed': 'changer',
        }
        event.account = None
        if event.type in accountfield_from_type:
            field = accountfield_from_type[event.type]
            if field:
                event.account = data.get(accountfield_from_type[event.type])
        else:
            self.log.warning("Received unrecognized event type '%s' "
                             "from Gerrit. Can not get account information." %
                             (event.type,))

        # This checks whether the event created or deleted a branch so
        # that Zuul may know to perform a reconfiguration on the
        # project.
        if (event.type == 'ref-updated' and
            ((not event.ref.startswith('refs/')) or
             event.ref.startswith('refs/heads'))):
            if event.oldrev == '0' * 40:
                event.branch_created = True
                event.branch = event.ref
            if event.newrev == '0' * 40:
                event.branch_deleted = True
                event.branch = event.ref

        self._getChange(event)
        self.connection.logEvent(event)
        self.connection.sched.addEvent(event)

    def _getChange(self, event):
        # Grab the change if we are managing the project or if it exists in the
        # cache as it may be a dependency
        if event.change_number:
            refresh = True
            if event.change_number not in self.connection._change_cache:
                refresh = False
                for tenant in self.connection.sched.abide.tenants.values():
                    # TODO(fungi): it would be better to have some simple means
                    # of inferring the hostname from the connection, or at
                    # least split this into separate method arguments, rather
                    # than assembling and passing in a baked string.
                    if (None, None) != tenant.getProject('/'.join((
                            self.connection.canonical_hostname,
                            event.project_name))):
                        refresh = True
                        break

            if refresh:
                # Call _getChange for the side effect of updating the
                # cache.  Note that this modifies Change objects outside
                # the main thread.
                # NOTE(jhesketh): Ideally we'd just remove the change from the
                # cache to denote that it needs updating. However the change
                # object is already used by Items and hence BuildSets etc. and
                # we need to update those objects by reference so that they
                # have the correct/new information and also avoid hitting
                # gerrit multiple times.
                self.connection._getChange(event.change_number,
                                           event.patch_number,
                                           refresh=True)

    def run(self):
        while True:
            if self._stopped:
                return
            try:
                self._handleEvent()
            except Exception:
                self.log.exception("Exception moving Gerrit event:")
            finally:
                self.connection.eventDone()


class GerritWatcher(threading.Thread):
    log = logging.getLogger("gerrit.GerritWatcher")
    poll_timeout = 500

    def __init__(self, gerrit_connection, username, hostname, port=29418,
                 keyfile=None, keepalive=60):
        threading.Thread.__init__(self)
        self.username = username
        self.keyfile = keyfile
        self.hostname = hostname
        self.port = port
        self.gerrit_connection = gerrit_connection
        self.keepalive = keepalive
        self._stopped = False

    def _read(self, fd):
        while True:
            l = fd.readline()
            data = json.loads(l)
            self.log.debug("Received data from Gerrit event stream: \n%s" %
                           pprint.pformat(data))
            self.gerrit_connection.addEvent(data)
            # Continue until all the lines received are consumed
            if fd._pos == fd._realpos:
                break

    def _listen(self, stdout, stderr):
        poll = select.poll()
        poll.register(stdout.channel)
        while not self._stopped:
            ret = poll.poll(self.poll_timeout)
            for (fd, event) in ret:
                if fd == stdout.channel.fileno():
                    if event == select.POLLIN:
                        self._read(stdout)
                    else:
                        raise Exception("event on ssh connection")

    def _run(self):
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            client.connect(self.hostname,
                           username=self.username,
                           port=self.port,
                           key_filename=self.keyfile)
            transport = client.get_transport()
            transport.set_keepalive(self.keepalive)

            stdin, stdout, stderr = client.exec_command("gerrit stream-events")

            self._listen(stdout, stderr)

            if not stdout.channel.exit_status_ready():
                # The stream-event is still running but we are done polling
                # on stdout most likely due to being asked to stop.
                # Try to stop the stream-events command sending Ctrl-C
                stdin.write("\x03")
                time.sleep(.2)
                if not stdout.channel.exit_status_ready():
                    # we're still not ready to exit, lets force the channel
                    # closed now.
                    stdout.channel.close()
            ret = stdout.channel.recv_exit_status()
            self.log.debug("SSH exit status: %s" % ret)

            if ret and ret not in [-1, 130]:
                raise Exception("Gerrit error executing stream-events")
        except Exception:
            self.log.exception("Exception on ssh event stream:")
            time.sleep(5)
        finally:
            # If we don't close on exceptions to connect we can leak the
            # connection and DoS Gerrit.
            client.close()

    def run(self):
        while not self._stopped:
            self._run()

    def stop(self):
        self.log.debug("Stopping watcher")
        self._stopped = True


class GerritConnection(BaseConnection):
    driver_name = 'gerrit'
    log = logging.getLogger("zuul.GerritConnection")
    iolog = logging.getLogger("zuul.GerritConnection.io")
    depends_on_re = re.compile(r"^Depends-On: (I[0-9a-f]{40})\s*$",
                               re.MULTILINE | re.IGNORECASE)
    replication_timeout = 300
    replication_retry_interval = 5

    def __init__(self, driver, connection_name, connection_config):
        super(GerritConnection, self).__init__(driver, connection_name,
                                               connection_config)
        if 'server' not in self.connection_config:
            raise Exception('server is required for gerrit connections in '
                            '%s' % self.connection_name)
        if 'user' not in self.connection_config:
            raise Exception('user is required for gerrit connections in '
                            '%s' % self.connection_name)

        self.user = self.connection_config.get('user')
        self.server = self.connection_config.get('server')
        self.canonical_hostname = self.connection_config.get(
            'canonical_hostname', self.server)
        self.port = int(self.connection_config.get('port', 29418))
        self.keyfile = self.connection_config.get('sshkey', None)
        self.keepalive = int(self.connection_config.get('keepalive', 60))
        self.watcher_thread = None
        self.event_queue = queue.Queue()
        self.client = None

        self.baseurl = self.connection_config.get('baseurl',
                                                  'https://%s' % self.server)
        default_gitweb_url_template = '{baseurl}/gitweb?' \
                                      'p={project.name}.git;' \
                                      'a=commitdiff;h={sha}'
        url_template = self.connection_config.get('gitweb_url_template',
                                                  default_gitweb_url_template)
        self.gitweb_url_template = url_template

        self._change_cache = {}
        self.projects = {}
        self.gerrit_event_connector = None
        self.source = driver.getSource(self)

    def getProject(self, name: str) -> Project:
        return self.projects.get(name)

    def addProject(self, project: Project) -> None:
        self.projects[project.name] = project

    def maintainCache(self, relevant):
        # This lets the user supply a list of change objects that are
        # still in use.  Anything in our cache that isn't in the supplied
        # list should be safe to remove from the cache.
        remove = {}
        for change_number, patchsets in self._change_cache.items():
            for patchset, change in patchsets.items():
                if change not in relevant:
                    remove.setdefault(change_number, [])
                    remove[change_number].append(patchset)
        for change_number, patchsets in remove.items():
            for patchset in patchsets:
                del self._change_cache[change_number][patchset]
            if not self._change_cache[change_number]:
                del self._change_cache[change_number]

    def getChange(self, event, refresh=False):
        if event.change_number:
            change = self._getChange(event.change_number, event.patch_number,
                                     refresh=refresh)
        elif event.ref and event.ref.startswith('refs/tags/'):
            project = self.source.getProject(event.project_name)
            change = Tag(project)
            change.tag = event.ref[len('refs/tags/'):]
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getWebUrl(project, sha=event.newrev)
        elif event.ref and not event.ref.startswith('refs/'):
            # Pre 2.13 Gerrit ref-updated events don't have branch prefixes.
            project = self.source.getProject(event.project_name)
            change = Branch(project)
            change.branch = event.ref
            change.ref = 'refs/heads/' + event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getWebUrl(project, sha=event.newrev)
        elif event.ref and event.ref.startswith('refs/heads/'):
            # From the timer trigger or Post 2.13 Gerrit
            project = self.source.getProject(event.project_name)
            change = Branch(project)
            change.ref = event.ref
            change.branch = event.ref[len('refs/heads/'):]
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getWebUrl(project, sha=event.newrev)
        elif event.ref:
            # catch-all ref (ie, not a branch or head)
            project = self.source.getProject(event.project_name)
            change = Ref(project)
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getWebUrl(project, sha=event.newrev)
        else:
            self.log.warning("Unable to get change for %s" % (event,))
            change = None
        return change

    def _getChange(self, number, patchset, refresh=False, history=None):
        change = self._change_cache.get(number, {}).get(patchset)
        if change and not refresh:
            return change
        if not change:
            change = GerritChange(None)
            change.number = number
            change.patchset = patchset
        self._change_cache.setdefault(change.number, {})
        self._change_cache[change.number][change.patchset] = change
        try:
            self._updateChange(change, history)
        except Exception:
            if self._change_cache.get(change.number, {}).get(change.patchset):
                del self._change_cache[change.number][change.patchset]
                if not self._change_cache[change.number]:
                    del self._change_cache[change.number]
            raise
        return change

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
            records.extend(self.simpleQuery(query))
        return records

    def _getNeededByFromCommit(self, change_id, change):
        records = []
        seen = set()
        query = 'message:%s' % change_id
        self.log.debug("Updating %s: Running query %s "
                       "to find changes needed-by" %
                       (change, query,))
        results = self.simpleQuery(query)
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

        # In case this change is already in the history we have a
        # cyclic dependency and don't need to update ourselves again
        # as this gets done in a previous frame of the call stack.
        # NOTE(jeblair): I don't think it's possible to hit this case
        # anymore as all paths hit the change cache first.
        if (history and change.number and change.patchset and
            (change.number, change.patchset) in history):
            self.log.debug("Change %s is in history" % (change,))
            return change

        self.log.info("Updating %s" % (change,))
        data = self.query(change.number)
        change._data = data

        if change.patchset is None:
            change.patchset = data['currentPatchSet']['number']

        if 'project' not in data:
            raise exceptions.ChangeNotFound(change.number, change.patchset)
        change.project = self.source.getProject(data['project'])
        change.branch = data['branch']
        change.url = data['url']
        max_ps = 0
        files = []
        for ps in data['patchSets']:
            if ps['number'] == change.patchset:
                change.ref = ps['ref']
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
        history.append((change.number, change.patchset))

        needs_changes = []
        if 'dependsOn' in data:
            parts = data['dependsOn'][0]['ref'].split('/')
            dep_num, dep_ps = parts[3], parts[4]
            self.log.debug("Updating %s: Getting git-dependent change %s,%s" %
                           (change, dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            # This is a git commit dependency. So we only ignore it if it is
            # already merged. So even if it is "ABANDONED", we should not
            # ignore it.
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)

        for record in self._getDependsOnFromCommit(data['commitMessage'],
                                                   change):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            self.log.debug("Updating %s: Getting commit-dependent "
                           "change %s,%s" %
                           (change, dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            if dep.open and dep not in needs_changes:
                needs_changes.append(dep)
        change.needs_changes = needs_changes

        needed_by_changes = []
        if 'neededBy' in data:
            for needed in data['neededBy']:
                parts = needed['ref'].split('/')
                dep_num, dep_ps = parts[3], parts[4]
                self.log.debug("Updating %s: Getting git-needed change %s,%s" %
                               (change, dep_num, dep_ps))
                dep = self._getChange(dep_num, dep_ps, history=history)
                if dep.open and dep.is_current_patchset:
                    needed_by_changes.append(dep)

        for record in self._getNeededByFromCommit(data['id'], change):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            self.log.debug("Updating %s: Getting commit-needed change %s,%s" %
                           (change, dep_num, dep_ps))
            # Because a commit needed-by may be a cross-repo
            # dependency, cause that change to refresh so that it will
            # reference the latest patchset of its Depends-On (this
            # change). In case the dep is already in history we already
            # refreshed this change so refresh is not needed in this case.
            refresh = (dep_num, dep_ps) not in history
            dep = self._getChange(
                dep_num, dep_ps, refresh=refresh, history=history)
            if dep.open and dep.is_current_patchset:
                needed_by_changes.append(dep)
        change.needed_by_changes = needed_by_changes

        return change

    def isMerged(self, change, head=None):
        self.log.debug("Checking if change %s is merged" % change)
        if not change.number:
            self.log.debug("Change has no number; considering it merged")
            # Good question.  It's probably ref-updated, which, ah,
            # means it's merged.
            return True

        data = self.query(change.number)
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

    def _waitForRefSha(self, project: Project,
                       ref: str, old_sha: str='') -> bool:
        # Wait for the ref to show up in the repo
        start = time.time()
        while time.time() - start < self.replication_timeout:
            sha = self.getRefSha(project, ref)
            if old_sha != sha:
                return True
            time.sleep(self.replication_retry_interval)
        return False

    def getRefSha(self, project: Project, ref: str) -> str:
        refs = {}  # type: Dict[str, str]
        try:
            refs = self.getInfoRefs(project)
        except Exception:
            self.log.exception("Exception looking for ref %s" %
                               ref)
        sha = refs.get(ref, '')
        return sha

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
                            if label['label'] not in allow_needs:
                                return False
                            continue
                        else:
                            # IMPOSSIBLE
                            return False
                else:
                    # CLOSED, RULE_ERROR
                    return False
        except Exception:
            self.log.exception("Exception determining whether change"
                               "%s can merge:" % change)
            return False
        return True

    def getProjectOpenChanges(self, project: Project) -> List[GerritChange]:
        # This is a best-effort function in case Gerrit is unable to return
        # a particular change.  It happens.
        query = "project:%s status:open" % (project.name,)
        self.log.debug("Running query %s to get project open changes" %
                       (query,))
        data = self.simpleQuery(query)
        changes = []  # type: List[GerritChange]
        for record in data:
            try:
                changes.append(
                    self._getChange(record['number'],
                                    record['currentPatchSet']['number']))
            except Exception:
                self.log.exception("Unable to query change %s" %
                                   (record.get('number'),))
        return changes

    def getProjectBranches(self, project: Project, tenant) -> List[str]:
        refs = self.getInfoRefs(project)
        heads = [str(k[len('refs/heads/'):]) for k in refs.keys()
                 if k.startswith('refs/heads/')]
        return heads

    def addEvent(self, data):
        return self.event_queue.put((time.time(), data))

    def getEvent(self):
        return self.event_queue.get()

    def eventDone(self):
        self.event_queue.task_done()

    def review(self, project, change, message, action={}):
        cmd = 'gerrit review --project %s' % project
        if message:
            cmd += ' --message %s' % shlex.quote(message)
        for key, val in action.items():
            if val is True:
                cmd += ' --%s' % key
            else:
                cmd += ' --label %s=%s' % (key, val)
        cmd += ' %s' % change
        out, err = self._ssh(cmd)
        return err

    def query(self, query):
        args = '--all-approvals --comments --commit-message'
        args += ' --current-patch-set --dependencies --files'
        args += ' --patch-sets --submit-records'
        cmd = 'gerrit query --format json %s %s' % (
            args, query)
        out, err = self._ssh(cmd)
        if not out:
            return False
        lines = out.split('\n')
        if not lines:
            return False
        data = json.loads(lines[0])
        if not data:
            return False
        self.iolog.debug("Received data from Gerrit query: \n%s" %
                         (pprint.pformat(data)))
        return data

    def simpleQuery(self, query):
        def _query_chunk(query):
            args = '--commit-message --current-patch-set'

            cmd = 'gerrit query --format json %s %s' % (
                args, query)
            out, err = self._ssh(cmd)
            if not out:
                return False
            lines = out.split('\n')
            if not lines:
                return False

            # filter out blank lines
            data = [json.loads(line) for line in lines
                    if line.startswith('{')]

            # check last entry for more changes
            more_changes = None
            if 'moreChanges' in data[-1]:
                more_changes = data[-1]['moreChanges']

            # we have to remove the statistics line
            del data[-1]

            if not data:
                return False, more_changes
            self.iolog.debug("Received data from Gerrit query: \n%s" %
                             (pprint.pformat(data)))
            return data, more_changes

        # gerrit returns 500 results by default, so implement paging
        # for large projects like nova
        alldata = []
        chunk, more_changes = _query_chunk(query)
        while(chunk):
            alldata.extend(chunk)
            if more_changes is None:
                # continue sortKey based (before Gerrit 2.9)
                resume = "resume_sortkey:'%s'" % chunk[-1]["sortKey"]
            elif more_changes:
                # continue moreChanges based (since Gerrit 2.9)
                resume = "-S %d" % len(alldata)
            else:
                # no more changes
                break

            chunk, more_changes = _query_chunk("%s %s" % (query, resume))
        return alldata

    def _uploadPack(self, project: Project) -> str:
        cmd = "git-upload-pack %s" % project.name
        out, err = self._ssh(cmd, "0000")
        return out

    def _open(self):
        if self.client:
            # Paramiko needs explicit closes, its possible we will open even
            # with an unclosed client so explicitly close here.
            self.client.close()
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            client.connect(self.server,
                           username=self.user,
                           port=self.port,
                           key_filename=self.keyfile)
            transport = client.get_transport()
            transport.set_keepalive(self.keepalive)
            self.client = client
        except Exception:
            client.close()
            self.client = None
            raise

    def _ssh(self, command, stdin_data=None):
        if not self.client:
            self._open()

        try:
            self.log.debug("SSH command:\n%s" % command)
            stdin, stdout, stderr = self.client.exec_command(command)
        except Exception:
            self._open()
            stdin, stdout, stderr = self.client.exec_command(command)

        if stdin_data:
            stdin.write(stdin_data)

        out = stdout.read().decode('utf-8')
        self.iolog.debug("SSH received stdout:\n%s" % out)

        ret = stdout.channel.recv_exit_status()
        self.log.debug("SSH exit status: %s" % ret)

        err = stderr.read().decode('utf-8')
        if err.strip():
            self.log.debug("SSH received stderr:\n%s" % err)

        if ret:
            self.log.debug("SSH received stdout:\n%s" % out)
            raise Exception("Gerrit error executing %s" % command)
        return (out, err)

    def getInfoRefs(self, project: Project) -> Dict[str, str]:
        try:
            data = self._uploadPack(project)
        except Exception:
            self.log.error("Cannot get references from %s" % project)
            raise  # keeps error information
        ret = {}
        read_advertisement = False
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

    def getGitUrl(self, project: Project) -> str:
        url = 'ssh://%s@%s:%s/%s' % (self.user, self.server, self.port,
                                     project.name)
        return url

    def _getWebUrl(self, project: Project, sha: str=None) -> str:
        return self.gitweb_url_template.format(
            baseurl=self.baseurl,
            project=project.getSafeAttributes(),
            sha=sha)

    def onLoad(self):
        self.log.debug("Starting Gerrit Connection/Watchers")
        self._start_watcher_thread()
        self._start_event_connector()

    def onStop(self):
        self.log.debug("Stopping Gerrit Connection/Watchers")
        self._stop_watcher_thread()
        self._stop_event_connector()

    def _stop_watcher_thread(self):
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.join()

    def _start_watcher_thread(self):
        self.watcher_thread = GerritWatcher(
            self,
            self.user,
            self.server,
            self.port,
            keyfile=self.keyfile,
            keepalive=self.keepalive)
        self.watcher_thread.start()

    def _stop_event_connector(self):
        if self.gerrit_event_connector:
            self.gerrit_event_connector.stop()
            self.gerrit_event_connector.join()

    def _start_event_connector(self):
        self.gerrit_event_connector = GerritEventConnector(self)
        self.gerrit_event_connector.start()


def getSchema():
    gerrit_connection = v.Any(str, v.Schema(dict))
    return gerrit_connection
