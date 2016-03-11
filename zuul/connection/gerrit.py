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
from six.moves import queue as Queue
import paramiko
import logging
import pprint
import voluptuous as v
import urllib2

from zuul.connection import BaseConnection
from zuul.model import TriggerEvent, Project, Change, Ref, NullChange
from zuul import exceptions


class GerritEventConnector(threading.Thread):
    """Move events from Gerrit to the scheduler."""

    log = logging.getLogger("zuul.GerritEventConnector")
    delay = 5.0

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
        event = TriggerEvent()
        event.type = data.get('type')
        event.trigger_name = 'gerrit'
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
            # TODO(jhesketh): Check if the project exists?
            # and self.connection.sched.getProject(event.project_name):

            # Call _getChange for the side effect of updating the
            # cache.  Note that this modifies Change objects outside
            # the main thread.
            # NOTE(jhesketh): Ideally we'd just remove the change from the
            # cache to denote that it needs updating. However the change
            # object is already used by Items and hence BuildSets etc. and
            # we need to update those objects by reference so that they have
            # the correct/new information and also avoid hitting gerrit
            # multiple times.
            self.connection._getChange(event.change_number,
                                       event.patch_number,
                                       refresh=True)
        self.connection.sched.addEvent(event)

    def run(self):
        while True:
            if self._stopped:
                return
            try:
                self._handleEvent()
            except:
                self.log.exception("Exception moving Gerrit event:")
            finally:
                self.connection.eventDone()


class GerritWatcher(threading.Thread):
    log = logging.getLogger("gerrit.GerritWatcher")

    def __init__(self, gerrit_connection, username, hostname, port=29418,
                 keyfile=None):
        threading.Thread.__init__(self)
        self.username = username
        self.keyfile = keyfile
        self.hostname = hostname
        self.port = port
        self.gerrit_connection = gerrit_connection
        self._stopped = False

    def _read(self, fd):
        l = fd.readline()
        data = json.loads(l)
        self.log.debug("Received data from Gerrit event stream: \n%s" %
                       pprint.pformat(data))
        self.gerrit_connection.addEvent(data)

    def _listen(self, stdout, stderr):
        poll = select.poll()
        poll.register(stdout.channel)
        while not self._stopped:
            ret = poll.poll()
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
            client.close()

            if ret and ret not in [-1, 130]:
                raise Exception("Gerrit error executing stream-events")
        except:
            self.log.exception("Exception on ssh event stream:")
            time.sleep(5)

    def run(self):
        while not self._stopped:
            self._run()

    def stop(self):
        self.log.debug("Stopping watcher")
        self._stopped = True


class GerritConnection(BaseConnection):
    driver_name = 'gerrit'
    log = logging.getLogger("connection.gerrit")
    depends_on_re = re.compile(r"^Depends-On: (I[0-9a-f]{40})\s*$",
                               re.MULTILINE | re.IGNORECASE)
    replication_timeout = 300
    replication_retry_interval = 5

    def __init__(self, connection_name, connection_config):
        super(GerritConnection, self).__init__(connection_name,
                                               connection_config)
        if 'server' not in self.connection_config:
            raise Exception('server is required for gerrit connections in '
                            '%s' % self.connection_name)
        if 'user' not in self.connection_config:
            raise Exception('user is required for gerrit connections in '
                            '%s' % self.connection_name)

        self.user = self.connection_config.get('user')
        self.server = self.connection_config.get('server')
        self.port = int(self.connection_config.get('port', 29418))
        self.keyfile = self.connection_config.get('sshkey', None)
        self.watcher_thread = None
        self.event_queue = None
        self.client = None

        self.baseurl = self.connection_config.get('baseurl',
                                                  'https://%s' % self.server)

        self._change_cache = {}
        self.projects = {}
        self.gerrit_event_connector = None

    def getProject(self, name):
        if name not in self.projects:
            self.projects[name] = Project(name)
        return self.projects[name]

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

    def getChange(self, event):
        if event.change_number:
            refresh = False
            change = self._getChange(event.change_number, event.patch_number,
                                     refresh=refresh)
        elif event.ref:
            project = self.getProject(event.project_name)
            change = Ref(project)
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self._getGitwebUrl(project, sha=event.newrev)
        else:
            # TODOv3(jeblair): we need to get the project from the event
            change = NullChange(project)
        return change

    def _getChange(self, number, patchset, refresh=False, history=None):
        key = '%s,%s' % (number, patchset)
        change = self._change_cache.get(key)
        if change and not refresh:
            return change
        if not change:
            change = Change(None)
            change.number = number
            change.patchset = patchset
        key = '%s,%s' % (change.number, change.patchset)
        self._change_cache[key] = change
        try:
            self._updateChange(change, history)
        except Exception:
            if key in self._change_cache:
                del self._change_cache[key]
            raise
        return change

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
            records.extend(self.simpleQuery(query))
        return records

    def _getNeededByFromCommit(self, change_id):
        records = []
        seen = set()
        query = 'message:%s' % change_id
        self.log.debug("Running query %s to find changes needed-by" %
                       (query,))
        results = self.simpleQuery(query)
        for result in results:
            for match in self.depends_on_re.findall(
                result['commitMessage']):
                if match != change_id:
                    continue
                key = (result['number'], result['currentPatchSet']['number'])
                if key in seen:
                    continue
                self.log.debug("Found change %s,%s needs %s from commit" %
                               (key[0], key[1], change_id))
                seen.add(key)
                records.append(result)
        return records

    def _updateChange(self, change, history=None):
        self.log.info("Updating information for %s,%s" %
                      (change.number, change.patchset))
        data = self.query(change.number)
        change._data = data

        if change.patchset is None:
            change.patchset = data['currentPatchSet']['number']

        if 'project' not in data:
            raise exceptions.ChangeNotFound(change.number, change.patchset)
        change.project = self.getProject(data['project'])
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
            self.log.debug("Getting git-dependent change %s,%s" %
                           (dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)

        for record in self._getDependsOnFromCommit(data['commitMessage']):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            if dep_num in history:
                raise Exception("Dependency cycle detected: %s in %s" % (
                    dep_num, history))
            self.log.debug("Getting commit-dependent change %s,%s" %
                           (dep_num, dep_ps))
            dep = self._getChange(dep_num, dep_ps, history=history)
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)
        change.needs_changes = needs_changes

        needed_by_changes = []
        if 'neededBy' in data:
            for needed in data['neededBy']:
                parts = needed['ref'].split('/')
                dep_num, dep_ps = parts[3], parts[4]
                dep = self._getChange(dep_num, dep_ps)
                if (not dep.is_merged) and dep.is_current_patchset:
                    needed_by_changes.append(dep)

        for record in self._getNeededByFromCommit(data['id']):
            dep_num = record['number']
            dep_ps = record['currentPatchSet']['number']
            self.log.debug("Getting commit-needed change %s,%s" %
                           (dep_num, dep_ps))
            # Because a commit needed-by may be a cross-repo
            # dependency, cause that change to refresh so that it will
            # reference the latest patchset of its Depends-On (this
            # change).
            dep = self._getChange(dep_num, dep_ps, refresh=True)
            if (not dep.is_merged) and dep.is_current_patchset:
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
        self.log.debug("Change %s status: %s" % (change, status))
        if status == 'MERGED':
            return True
        return False

    def _waitForRefSha(self, project, ref, old_sha=''):
        # Wait for the ref to show up in the repo
        start = time.time()
        while time.time() - start < self.replication_timeout:
            sha = self.getRefSha(project.name, ref)
            if old_sha != sha:
                return True
            time.sleep(self.replication_retry_interval)
        return False

    def getRefSha(self, project, ref):
        refs = {}
        try:
            refs = self.getInfoRefs(project)
        except:
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

    def getProjectOpenChanges(self, project):
        # This is a best-effort function in case Gerrit is unable to return
        # a particular change.  It happens.
        query = "project:%s status:open" % (project.name,)
        self.log.debug("Running query %s to get project open changes" %
                       (query,))
        data = self.simpleQuery(query)
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

    def addEvent(self, data):
        return self.event_queue.put((time.time(), data))

    def getEvent(self):
        return self.event_queue.get()

    def eventDone(self):
        self.event_queue.task_done()

    def review(self, project, change, message, action={}):
        cmd = 'gerrit review --project %s' % project
        if message:
            cmd += ' --message "%s"' % message
        for key, val in action.items():
            if val is True:
                cmd += ' --%s' % key
            else:
                cmd += ' --%s %s' % (key, val)
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
        self.log.debug("Received data from Gerrit query: \n%s" %
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
            self.log.debug("Received data from Gerrit query: \n%s" %
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

    def _open(self):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(self.server,
                       username=self.user,
                       port=self.port,
                       key_filename=self.keyfile)
        self.client = client

    def _ssh(self, command, stdin_data=None):
        if not self.client:
            self._open()

        try:
            self.log.debug("SSH command:\n%s" % command)
            stdin, stdout, stderr = self.client.exec_command(command)
        except:
            self._open()
            stdin, stdout, stderr = self.client.exec_command(command)

        if stdin_data:
            stdin.write(stdin_data)

        out = stdout.read()
        self.log.debug("SSH received stdout:\n%s" % out)

        ret = stdout.channel.recv_exit_status()
        self.log.debug("SSH exit status: %s" % ret)

        err = stderr.read()
        self.log.debug("SSH received stderr:\n%s" % err)
        if ret:
            raise Exception("Gerrit error executing %s" % command)
        return (out, err)

    def getInfoRefs(self, project):
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

    def getGitUrl(self, project):
        url = 'ssh://%s@%s:%s/%s' % (self.user, self.server, self.port,
                                     project.name)
        return url

    def getGitwebUrl(self, project, sha=None):
        url = '%s/gitweb?p=%s.git' % (self.baseurl, project)
        if sha:
            url += ';a=commitdiff;h=' + sha
        return url

    def onLoad(self):
        self.log.debug("Starting Gerrit Conncetion/Watchers")
        self._start_watcher_thread()
        self._start_event_connector()

    def onStop(self):
        self.log.debug("Stopping Gerrit Conncetion/Watchers")
        self._stop_watcher_thread()
        self._stop_event_connector()

    def _stop_watcher_thread(self):
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.join()

    def _start_watcher_thread(self):
        self.event_queue = Queue.Queue()
        self.watcher_thread = GerritWatcher(
            self,
            self.user,
            self.server,
            self.port,
            keyfile=self.keyfile)
        self.watcher_thread.start()

    def _stop_event_connector(self):
        if self.gerrit_event_connector:
            self.gerrit_event_connector.stop()
            self.gerrit_event_connector.join()

    def _start_event_connector(self):
        self.gerrit_event_connector = GerritEventConnector(self)
        self.gerrit_event_connector.start()


def getSchema():
    gerrit_connection = v.Any(str, v.Schema({}, extra=True))
    return gerrit_connection
