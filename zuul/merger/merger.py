# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013-2014 OpenStack Foundation
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

from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
import logging
import os
import re
import shutil
import time

import git
import gitdb

import zuul.model

NULL_REF = '0000000000000000000000000000000000000000'


def reset_repo_to_head(repo):
    # This lets us reset the repo even if there is a file in the root
    # directory named 'HEAD'.  Currently, GitPython does not allow us
    # to instruct it to always include the '--' to disambiguate.  This
    # should no longer be necessary if this PR merges:
    #   https://github.com/gitpython-developers/GitPython/pull/319
    try:
        repo.git.reset('--hard', 'HEAD', '--')
    except git.GitCommandError as e:
        # git nowadays may use 1 as status to indicate there are still unstaged
        # modifications after the reset
        if e.status != 1:
            raise


def redact_url(url):
    parsed = urlsplit(url)
    if parsed.password is None:
        return url

    # items[1] is the netloc containing credentials and hostname
    items = list(parsed)
    items[1] = re.sub('.*@', '******@', items[1])
    return urlunsplit(items)


@contextmanager
def timeout_handler(path):
    try:
        yield
    except git.exc.GitCommandError as e:
        if e.status == -9:
            # Timeout.  The repo could be in a bad state, so delete it.
            shutil.rmtree(path)
        raise


class Repo(object):
    def __init__(self, remote, local, email, username, speed_limit, speed_time,
                 sshkey=None, cache_path=None, logger=None, git_timeout=300,
                 retry_attempts=3, retry_interval=30):
        if logger is None:
            self.log = logging.getLogger("zuul.Repo")
        else:
            self.log = logger
        self.env = {
            'GIT_HTTP_LOW_SPEED_LIMIT': speed_limit,
            'GIT_HTTP_LOW_SPEED_TIME': speed_time,
        }
        self.git_timeout = git_timeout
        if sshkey:
            self.env['GIT_SSH_COMMAND'] = 'ssh -i %s' % (sshkey,)

        self.remote_url = remote
        self.local_path = local
        self.email = email
        self.username = username
        self.cache_path = cache_path
        self._initialized = False
        self.retry_attempts = retry_attempts
        self.retry_interval = retry_interval
        try:
            self._ensure_cloned()
            self._git_set_remote_url(
                git.Repo(self.local_path), self.remote_url)
        except Exception:
            self.log.exception("Unable to initialize repo for %s" % remote)

    def _ensure_cloned(self):
        repo_is_cloned = os.path.exists(os.path.join(self.local_path, '.git'))
        if self._initialized and repo_is_cloned:
            try:
                # validate that the repo isn't corrupt
                git.Repo(self.local_path)
                return
            except Exception:
                # the repo is corrupt, delete the local path
                shutil.rmtree(self.local_path)
                repo_is_cloned = False
                self._initialized = False

        # If the repo does not exist, clone the repo.
        rewrite_url = False
        if not repo_is_cloned:
            if self.cache_path:
                clone_url = self.cache_path
                rewrite_url = True
            else:
                clone_url = self.remote_url

            self.log.debug("Cloning from %s to %s" % (
                redact_url(clone_url), self.local_path))
            self._git_clone(clone_url)

        repo = git.Repo(self.local_path)
        repo.git.update_environment(**self.env)
        # Create local branches corresponding to all the remote branches
        if not repo_is_cloned:
            origin = repo.remotes.origin
            for ref in origin.refs:
                if ref.remote_head == 'HEAD':
                    continue
                repo.create_head(ref.remote_head, ref, force=True)
        with repo.config_writer() as config_writer:
            if self.email:
                config_writer.set_value('user', 'email', self.email)
            if self.username:
                config_writer.set_value('user', 'name', self.username)
            config_writer.write()
        if rewrite_url:
            self._git_set_remote_url(repo, self.remote_url)
        self._initialized = True

    def isInitialized(self):
        return self._initialized

    def _git_clone(self, url):
        mygit = git.cmd.Git(os.getcwd())
        mygit.update_environment(**self.env)

        for attempt in range(1, self.retry_attempts + 1):
            try:
                with timeout_handler(self.local_path):
                    mygit.clone(git.cmd.Git.polish_url(url), self.local_path,
                                kill_after_timeout=self.git_timeout)
                break
            except Exception as e:
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_interval)
                    self.log.warning("Retry %s: Clone %s" % (
                        attempt, self.local_path))
                else:
                    raise

    def _git_fetch(self, repo, remote, ref=None, **kwargs):
        for attempt in range(1, self.retry_attempts + 1):
            try:
                with timeout_handler(self.local_path):
                    repo.git.fetch(remote, ref,
                                   kill_after_timeout=self.git_timeout,
                                   **kwargs)
                break
            except Exception as e:
                if attempt < self.retry_attempts:
                    if 'fatal: bad config' in e.stderr:
                        # This error can be introduced by a merge conflict
                        # in the .gitmodules which was left by the last
                        # merge operation. In this case reset and clean
                        # the repo and try again immediately.
                        reset_repo_to_head(repo)
                        repo.git.clean('-x', '-f', '-d')
                    else:
                        time.sleep(self.retry_interval)
                    self.log.exception("Retry %s: Fetch %s %s %s" % (
                        attempt, self.local_path, remote, ref))
                    self._ensure_cloned()
                else:
                    raise

    def _git_set_remote_url(self, repo, url):
        with repo.remotes.origin.config_writer as config_writer:
            config_writer.set('url', url)

    def createRepoObject(self):
        self._ensure_cloned()
        repo = git.Repo(self.local_path)
        repo.git.update_environment(**self.env)
        return repo

    def reset(self):
        self.log.debug("Resetting repository %s" % self.local_path)
        self.update()
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        seen = set()
        head = None
        stale_refs = origin.stale_refs
        # Update our local heads to match the remote, and pick one to
        # reset the repo to.  We don't delete anything at this point
        # because we want to make sure the repo is in a state stable
        # enough for git to operate.
        for ref in origin.refs:
            if ref.remote_head == 'HEAD':
                continue
            if ref in stale_refs:
                continue
            repo.create_head(ref.remote_head, ref, force=True)
            seen.add(ref.remote_head)
            if head is None:
                head = ref.remote_head
        self.log.debug("Reset to %s", head)
        repo.head.reference = head
        reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')
        for ref in stale_refs:
            self.log.debug("Delete stale ref %s", ref.remote_head)
            # A stale ref means the upstream branch (e.g. foobar) was deleted
            # so we need to delete both our local head (if existing) and the
            # remote tracking head. Both repo.heads and ref.remote_head
            # contain the pure branch name so they can be compared easily.
            for head in repo.heads:
                if head.name == ref.remote_head:
                    repo.delete_head(ref.remote_head, force=True)
                    break
            git.refs.RemoteReference.delete(repo, ref, force=True)

    def prune(self):
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        stale_refs = origin.stale_refs
        if stale_refs:
            self.log.debug("Pruning stale refs: %s", stale_refs)
            git.refs.RemoteReference.delete(repo, force=True, *stale_refs)

    def getBranchHead(self, branch):
        repo = self.createRepoObject()
        branch_head = repo.heads[branch]
        return branch_head.commit

    def hasBranch(self, branch):
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        return branch in origin.refs

    def getBranches(self):
        # TODO(jeblair): deprecate with override-branch; replaced by
        # getRefs().
        repo = self.createRepoObject()
        return [x.name for x in repo.heads]

    def getCommitFromRef(self, refname):
        repo = self.createRepoObject()
        if refname not in repo.refs:
            return None
        ref = repo.refs[refname]
        return ref.commit

    def getRefs(self):
        repo = self.createRepoObject()
        return repo.refs

    def setRef(self, path, hexsha, repo=None):
        self.log.debug("Create reference %s at %s in %s",
                       path, hexsha, self.local_path)
        if repo is None:
            repo = self.createRepoObject()
        binsha = gitdb.util.to_bin_sha(hexsha)
        obj = git.objects.Object.new_from_sha(repo, binsha)
        git.refs.Reference.create(repo, path, obj, force=True)

    def setRefs(self, refs, keep_remotes=False):
        repo = self.createRepoObject()
        current_refs = {}
        for ref in repo.refs:
            current_refs[ref.path] = ref
        unseen = set(current_refs.keys())
        for path, hexsha in refs.items():
            self.setRef(path, hexsha, repo)
            unseen.discard(path)
            ref = current_refs.get(path)
            if keep_remotes and ref:
                unseen.discard('refs/remotes/origin/{}'.format(ref.name))
        for path in unseen:
            self.deleteRef(path, repo)

    def setRemoteRef(self, branch, rev):
        repo = self.createRepoObject()
        try:
            origin_ref = repo.remotes.origin.refs[branch]
        except IndexError:
            self.log.warning("No remote ref found for branch %s", branch)
            return
        self.log.debug("Updating remote reference %s to %s", origin_ref, rev)
        origin_ref.commit = rev

    def deleteRef(self, path, repo=None):
        if repo is None:
            repo = self.createRepoObject()
        self.log.debug("Delete reference %s", path)
        git.refs.SymbolicReference.delete(repo, path)

    def checkout(self, ref):
        repo = self.createRepoObject()
        self.log.debug("Checking out %s" % ref)
        # Perform a hard reset before checking out so that we clean up
        # anything that might be left over from a merge.
        reset_repo_to_head(repo)
        repo.git.checkout(ref)
        return repo.head.commit

    def cherryPick(self, ref):
        repo = self.createRepoObject()
        self.log.debug("Cherry-picking %s" % ref)
        self.fetch(ref)
        repo.git.cherry_pick("FETCH_HEAD")
        return repo.head.commit

    def merge(self, ref, strategy=None):
        repo = self.createRepoObject()
        args = []
        if strategy:
            args += ['-s', strategy]
        args.append('FETCH_HEAD')
        self.fetch(ref)
        self.log.debug("Merging %s with args %s" % (ref, args))
        repo.git.merge(*args)
        return repo.head.commit

    def fetch(self, ref):
        repo = self.createRepoObject()
        # NOTE: The following is currently not applicable, but if we
        # switch back to fetch methods from GitPython, we need to
        # consider it:
        #   The git.remote.fetch method may read in git progress info and
        #   interpret it improperly causing an AssertionError. Because the
        #   data was fetched properly subsequent fetches don't seem to fail.
        #   So try again if an AssertionError is caught.
        self._git_fetch(repo, 'origin', ref)

    def fetchFrom(self, repository, ref):
        repo = self.createRepoObject()
        self._git_fetch(repo, repository, ref)

    def push(self, local, remote):
        repo = self.createRepoObject()
        self.log.debug("Pushing %s:%s to %s" % (local, remote,
                                                self.remote_url))
        repo.remotes.origin.push('%s:%s' % (local, remote))

    def update(self):
        repo = self.createRepoObject()
        self.log.debug("Updating repository %s" % self.local_path)
        if repo.git.version_info[:2] < (1, 9):
            # Before 1.9, 'git fetch --tags' did not include the
            # behavior covered by 'git --fetch', so we run both
            # commands in that case.  Starting with 1.9, 'git fetch
            # --tags' is all that is necessary.  See
            # https://github.com/git/git/blob/master/Documentation/RelNotes/1.9.0.txt#L18-L20
            self._git_fetch(repo, 'origin')
        self._git_fetch(repo, 'origin', tags=True)

    def getFiles(self, files, dirs=[], branch=None, commit=None):
        ret = {}
        repo = self.createRepoObject()
        if branch:
            tree = repo.heads[branch].commit.tree
        else:
            tree = repo.commit(commit).tree
        for fn in files:
            if fn in tree:
                ret[fn] = tree[fn].data_stream.read().decode('utf8')
            else:
                ret[fn] = None
        if dirs:
            for dn in dirs:
                if dn not in tree:
                    continue
                for blob in tree[dn].traverse():
                    if blob.path.endswith(".yaml"):
                        ret[blob.path] = blob.data_stream.read().decode(
                            'utf-8')
        return ret

    def getFilesChanges(self, branch, tosha=None):
        repo = self.createRepoObject()
        files = set()
        head = repo.heads[branch].commit
        files.update(set(head.stats.files.keys()))
        if tosha:
            for cmt in head.iter_parents():
                if cmt.hexsha == tosha:
                    break
                files.update(set(cmt.stats.files.keys()))
        return list(files)

    def deleteRemote(self, remote):
        repo = self.createRepoObject()
        repo.delete_remote(repo.remotes[remote])

    def setRemoteUrl(self, url):
        if self.remote_url == url:
            return
        self.log.debug("Set remote url to %s" % redact_url(url))
        self.remote_url = url
        self._git_set_remote_url(self.createRepoObject(), self.remote_url)


class Merger(object):
    def __init__(self, working_root, connections, email, username,
                 speed_limit, speed_time, cache_root=None, logger=None,
                 execution_context=False):
        self.logger = logger
        if logger is None:
            self.log = logging.getLogger("zuul.Merger")
        else:
            self.log = logger
        self.repos = {}
        self.working_root = working_root
        if not os.path.exists(working_root):
            os.makedirs(working_root)
        self.connections = connections
        self.email = email
        self.username = username
        self.speed_limit = speed_limit
        self.speed_time = speed_time
        self.cache_root = cache_root
        # Flag to determine if the merger is used for preparing repositories
        # for job execution. This flag can be used to enable executor specific
        # behavior e.g. to keep the 'origin' remote intact.
        self.execution_context = execution_context

    def _addProject(self, hostname, project_name, url, sshkey):
        repo = None
        key = '/'.join([hostname, project_name])
        try:
            path = os.path.join(self.working_root, hostname, project_name)
            if self.cache_root:
                cache_path = os.path.join(self.cache_root, hostname,
                                          project_name)
            else:
                cache_path = None
            repo = Repo(
                url, path, self.email, self.username, self.speed_limit,
                self.speed_time, sshkey, cache_path, self.logger)

            self.repos[key] = repo
        except Exception:
            self.log.exception("Unable to add project %s/%s" %
                               (hostname, project_name))
        return repo

    def getRepo(self, connection_name, project_name):
        source = self.connections.getSource(connection_name)
        project = source.getProject(project_name)
        hostname = project.canonical_hostname
        url = source.getGitUrl(project)
        key = '/'.join([hostname, project_name])
        if key in self.repos:
            repo = self.repos[key]
            repo.setRemoteUrl(url)
            return repo
        sshkey = self.connections.connections.get(connection_name).\
            connection_config.get('sshkey')
        if not url:
            raise Exception("Unable to set up repo for project %s/%s"
                            " without a url" %
                            (connection_name, project_name,))
        return self._addProject(hostname, project_name, url, sshkey)

    def updateRepo(self, connection_name, project_name):
        repo = self.getRepo(connection_name, project_name)
        try:
            self.log.info("Updating local repository %s/%s",
                          connection_name, project_name)
            repo.reset()
        except Exception:
            self.log.exception("Unable to update %s/%s",
                               connection_name, project_name)

    def checkoutBranch(self, connection_name, project_name, branch):
        self.log.info("Checking out %s/%s branch %s",
                      connection_name, project_name, branch)
        repo = self.getRepo(connection_name, project_name)
        repo.checkout(branch)

    def _saveRepoState(self, connection_name, project_name, repo,
                       repo_state, recent):
        projects = repo_state.setdefault(connection_name, {})
        project = projects.setdefault(project_name, {})
        for ref in repo.getRefs():
            if ref.path.startswith('refs/zuul/'):
                continue
            if ref.path.startswith('refs/remotes/'):
                continue
            if ref.path.startswith('refs/heads/'):
                branch = ref.path[len('refs/heads/'):]
                key = (connection_name, project_name, branch)
                if key not in recent:
                    recent[key] = ref.object
            project[ref.path] = ref.object.hexsha

    def _alterRepoState(self, connection_name, project_name,
                        repo_state, path, hexsha):
        projects = repo_state.setdefault(connection_name, {})
        project = projects.setdefault(project_name, {})
        if hexsha == NULL_REF:
            if path in project:
                del project[path]
        else:
            project[path] = hexsha

    def _restoreRepoState(self, connection_name, project_name, repo,
                          repo_state):
        projects = repo_state.get(connection_name, {})
        project = projects.get(project_name, {})
        if not project:
            # We don't have a state for this project.
            return
        self.log.debug("Restore repo state for project %s/%s",
                       connection_name, project_name)
        repo.setRefs(project, keep_remotes=self.execution_context)

    def _mergeChange(self, item, ref):
        repo = self.getRepo(item['connection'], item['project'])
        try:
            repo.checkout(ref)
        except Exception:
            self.log.exception("Unable to checkout %s" % ref)
            return None

        try:
            mode = item['merge_mode']
            if mode == zuul.model.MERGER_MERGE:
                commit = repo.merge(item['ref'])
            elif mode == zuul.model.MERGER_MERGE_RESOLVE:
                commit = repo.merge(item['ref'], 'resolve')
            elif mode == zuul.model.MERGER_CHERRY_PICK:
                commit = repo.cherryPick(item['ref'])
            else:
                raise Exception("Unsupported merge mode: %s" % mode)
        except git.GitCommandError:
            # Log git exceptions at debug level because they are
            # usually benign merge conflicts
            self.log.debug("Unable to merge %s" % item, exc_info=True)
            return None
        except Exception:
            self.log.exception("Exception while merging a change:")
            return None

        return commit

    def _mergeItem(self, item, recent, repo_state):
        self.log.debug("Processing ref %s for project %s/%s / %s uuid %s" %
                       (item['ref'], item['connection'],
                        item['project'], item['branch'],
                        item['buildset_uuid']))
        repo = self.getRepo(item['connection'], item['project'])
        key = (item['connection'], item['project'], item['branch'])

        # We need to merge the change
        # Get the most recent commit for this project-branch
        base = recent.get(key)
        if not base:
            # There is none, so use the branch tip
            # we need to reset here in order to call getBranchHead
            self.log.debug("No base commit found for %s" % (key,))
            try:
                repo.reset()
            except Exception:
                self.log.exception("Unable to reset repo %s" % repo)
                return None
            self._restoreRepoState(item['connection'], item['project'], repo,
                                   repo_state)

            base = repo.getBranchHead(item['branch'])
            # Save the repo state so that later mergers can repeat
            # this process.
            self._saveRepoState(item['connection'], item['project'], repo,
                                repo_state, recent)
        else:
            self.log.debug("Found base commit %s for %s" % (base, key,))

        if self.execution_context:
            # Set origin branch to the rev of the current (speculative) base.
            # This allows tools to determine the commits that are part of a
            # change by looking at origin/master..master.
            repo.setRemoteRef(item['branch'], base)

        # Merge the change
        commit = self._mergeChange(item, base)
        if not commit:
            return None
        # Store this commit as the most recent for this project-branch
        recent[key] = commit
        return commit

    def mergeChanges(self, items, files=None, dirs=None, repo_state=None):
        # connection+project+branch -> commit
        recent = {}
        commit = None
        read_files = []
        # connection -> project -> ref -> commit
        if repo_state is None:
            repo_state = {}
        for item in items:
            self.log.debug("Merging for change %s,%s" %
                           (item["number"], item["patchset"]))
            commit = self._mergeItem(item, recent, repo_state)
            if not commit:
                return None
            if files or dirs:
                repo = self.getRepo(item['connection'], item['project'])
                repo_files = repo.getFiles(files, dirs, commit=commit)
                read_files.append(dict(
                    connection=item['connection'],
                    project=item['project'],
                    branch=item['branch'],
                    files=repo_files))
        ret_recent = {}
        for k, v in recent.items():
            ret_recent[k] = v.hexsha
        return commit.hexsha, read_files, repo_state, ret_recent

    def setRepoState(self, items, repo_state):
        # Sets the repo state for the items
        seen = set()
        for item in items:
            repo = self.getRepo(item['connection'], item['project'])
            key = (item['connection'], item['project'], item['branch'])

            if key in seen:
                continue

            repo.reset()
            self._restoreRepoState(item['connection'], item['project'], repo,
                                   repo_state)

    def getRepoState(self, items):
        # Gets the repo state for items.  Generally this will be
        # called in any non-change pipeline.  We will return the repo
        # state for each item, but manipulated with any information in
        # the item (eg, if it creates a ref, that will be in the repo
        # state regardless of the actual state).
        seen = set()
        recent = {}
        repo_state = {}
        for item in items:
            repo = self.getRepo(item['connection'], item['project'])
            key = (item['connection'], item['project'], item['branch'])
            if key not in seen:
                try:
                    repo.reset()
                except Exception:
                    self.log.exception("Unable to reset repo %s" % repo)
                    return (False, {})

                self._saveRepoState(item['connection'], item['project'], repo,
                                    repo_state, recent)

            if item.get('newrev'):
                # This is a ref update rather than a branch tip, so make sure
                # our returned state includes this change.
                self._alterRepoState(item['connection'], item['project'],
                                     repo_state, item['ref'], item['newrev'])
        return (True, repo_state)

    def getFiles(self, connection_name, project_name, branch, files, dirs=[]):
        repo = self.getRepo(connection_name, project_name)
        return repo.getFiles(files, dirs, branch=branch)

    def getFilesChanges(self, connection_name, project_name, branch,
                        tosha=None):
        repo = self.getRepo(connection_name, project_name)
        return repo.getFilesChanges(branch, tosha)
