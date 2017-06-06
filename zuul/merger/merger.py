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

import git
import gitdb
import os
import logging

import zuul.model


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


class ZuulReference(git.Reference):
    _common_path_default = "refs/zuul"
    _points_to_commits_only = True


class Repo(object):
    log = logging.getLogger("zuul.Repo")

    def __init__(self, remote, local, email, username):
        self.remote_url = remote
        self.local_path = local
        self.email = email
        self.username = username
        self._initialized = False
        try:
            self._ensure_cloned()
        except:
            self.log.exception("Unable to initialize repo for %s" % remote)

    def _ensure_cloned(self):
        repo_is_cloned = os.path.exists(os.path.join(self.local_path, '.git'))
        if self._initialized and repo_is_cloned:
            return
        # If the repo does not exist, clone the repo.
        if not repo_is_cloned:
            self.log.debug("Cloning from %s to %s" % (self.remote_url,
                                                      self.local_path))
            git.Repo.clone_from(self.remote_url, self.local_path)
        repo = git.Repo(self.local_path)
        with repo.config_writer() as config_writer:
            if self.email:
                config_writer.set_value('user', 'email', self.email)
            if self.username:
                config_writer.set_value('user', 'name', self.username)
            config_writer.write()
        self._initialized = True

    def isInitialized(self):
        return self._initialized

    def createRepoObject(self):
        self._ensure_cloned()
        repo = git.Repo(self.local_path)
        return repo

    def reset(self):
        self.log.debug("Resetting repository %s" % self.local_path)
        self.update()
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        for ref in origin.refs:
            if ref.remote_head == 'HEAD':
                continue
            repo.create_head(ref.remote_head, ref, force=True)

        # try reset to remote HEAD (usually origin/master)
        # If it fails, pick the first reference
        try:
            repo.head.reference = origin.refs['HEAD']
        except IndexError:
            repo.head.reference = origin.refs[0]
        reset_repo_to_head(repo)
        repo.git.clean('-x', '-f', '-d')

    def prune(self):
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        stale_refs = origin.stale_refs
        if stale_refs:
            self.log.debug("Pruning stale refs: %s", stale_refs)
            git.refs.RemoteReference.delete(repo, *stale_refs)

    def getBranchHead(self, branch):
        repo = self.createRepoObject()
        branch_head = repo.heads[branch]
        return branch_head.commit

    def hasBranch(self, branch):
        repo = self.createRepoObject()
        origin = repo.remotes.origin
        return branch in origin.refs

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
        if repo is None:
            repo = self.createRepoObject()
        binsha = gitdb.util.to_bin_sha(hexsha)
        obj = git.objects.Object.new_from_sha(repo, binsha)
        self.log.debug("Create reference %s", path)
        git.refs.Reference.create(repo, path, obj, force=True)

    def setRefs(self, refs):
        repo = self.createRepoObject()
        current_refs = {}
        for ref in repo.refs:
            current_refs[ref.path] = ref
        unseen = set(current_refs.keys())
        for path, hexsha in refs.items():
            self.setRef(path, hexsha, repo)
            unseen.discard(path)
        for path in unseen:
            self.log.debug("Delete reference %s", path)
            git.refs.SymbolicReference.delete(repo, ref.path)

    def checkout(self, ref):
        repo = self.createRepoObject()
        self.log.debug("Checking out %s" % ref)
        repo.head.reference = ref
        reset_repo_to_head(repo)
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
        # The git.remote.fetch method may read in git progress info and
        # interpret it improperly causing an AssertionError. Because the
        # data was fetched properly subsequent fetches don't seem to fail.
        # So try again if an AssertionError is caught.
        origin = repo.remotes.origin
        try:
            origin.fetch(ref)
        except AssertionError:
            origin.fetch(ref)

    def fetchFrom(self, repository, refspec):
        repo = self.createRepoObject()
        repo.git.fetch(repository, refspec)

    def createZuulRef(self, ref, commit='HEAD'):
        repo = self.createRepoObject()
        self.log.debug("CreateZuulRef %s at %s on %s" % (ref, commit, repo))
        ref = ZuulReference.create(repo, ref, commit)
        return ref.commit

    def push(self, local, remote):
        repo = self.createRepoObject()
        self.log.debug("Pushing %s:%s to %s" % (local, remote,
                                                self.remote_url))
        repo.remotes.origin.push('%s:%s' % (local, remote))

    def update(self):
        repo = self.createRepoObject()
        self.log.debug("Updating repository %s" % self.local_path)
        origin = repo.remotes.origin
        if repo.git.version_info[:2] < (1, 9):
            # Before 1.9, 'git fetch --tags' did not include the
            # behavior covered by 'git --fetch', so we run both
            # commands in that case.  Starting with 1.9, 'git fetch
            # --tags' is all that is necessary.  See
            # https://github.com/git/git/blob/master/Documentation/RelNotes/1.9.0.txt#L18-L20
            origin.fetch()
        origin.fetch(tags=True)

    def getFiles(self, files, branch=None, commit=None):
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
        return ret


class Merger(object):
    log = logging.getLogger("zuul.Merger")

    def __init__(self, working_root, connections, email, username):
        self.repos = {}
        self.working_root = working_root
        if not os.path.exists(working_root):
            os.makedirs(working_root)
        self.connections = connections
        self.email = email
        self.username = username

    def _get_ssh_cmd(self, connection_name):
        sshkey = self.connections.connections.get(connection_name).\
            connection_config.get('sshkey')
        if sshkey:
            return 'ssh -i %s' % sshkey
        else:
            return None

    def _setGitSsh(self, connection_name):
        wrapper_name = '.ssh_wrapper_%s' % connection_name
        name = os.path.join(self.working_root, wrapper_name)
        if os.path.isfile(name):
            os.environ['GIT_SSH'] = name
        elif 'GIT_SSH' in os.environ:
            del os.environ['GIT_SSH']

    def _addProject(self, hostname, project_name, url):
        repo = None
        key = '/'.join([hostname, project_name])
        try:
            path = os.path.join(self.working_root, hostname, project_name)
            repo = Repo(url, path, self.email, self.username)

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
            return self.repos[key]
        if not url:
            raise Exception("Unable to set up repo for project %s/%s"
                            " without a url" %
                            (connection_name, project_name,))
        return self._addProject(hostname, project_name, url)

    def updateRepo(self, connection_name, project_name):
        # TODOv3(jhesketh): Reimplement
        # da90a50b794f18f74de0e2c7ec3210abf79dda24 after merge..
        # Likely we'll handle connection context per projects differently.
        # self._setGitSsh()
        repo = self.getRepo(connection_name, project_name)
        try:
            self.log.info("Updating local repository %s/%s",
                          connection_name, project_name)
            repo.reset()
        except Exception:
            self.log.exception("Unable to update %s/%s",
                               connection_name, project_name)

    def checkoutBranch(self, connection_name, project_name, branch):
        repo = self.getRepo(connection_name, project_name)
        if repo.hasBranch(branch):
            self.log.info("Checking out branch %s of %s/%s" %
                          (branch, connection_name, project_name))
            head = repo.getBranchHead(branch)
            repo.checkout(head)
        else:
            raise Exception("Project %s/%s does not have branch %s" %
                            (connection_name, project_name, branch))

    def _saveRepoState(self, connection_name, project_name, repo,
                       repo_state):
        projects = repo_state.setdefault(connection_name, {})
        project = projects.setdefault(project_name, {})
        if project:
            # We already have a state for this project.
            return
        for ref in repo.getRefs():
            if ref.path.startswith('refs/zuul'):
                continue
            if ref.path.startswith('refs/remotes'):
                continue
            project[ref.path] = ref.object.hexsha

    def _restoreRepoState(self, connection_name, project_name, repo,
                          repo_state):
        projects = repo_state.get(connection_name, {})
        project = projects.get(project_name, {})
        if not project:
            # We don't have a state for this project.
            return
        self.log.debug("Restore repo state for project %s/%s",
                       connection_name, project_name)
        repo.setRefs(project)

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
                commit = repo.merge(item['refspec'])
            elif mode == zuul.model.MERGER_MERGE_RESOLVE:
                commit = repo.merge(item['refspec'], 'resolve')
            elif mode == zuul.model.MERGER_CHERRY_PICK:
                commit = repo.cherryPick(item['refspec'])
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
        self.log.debug("Processing refspec %s for project %s/%s / %s ref %s" %
                       (item['refspec'], item['connection'],
                        item['project'], item['branch'], item['ref']))
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
                                repo_state)
        else:
            self.log.debug("Found base commit %s for %s" % (base, key,))
        # Merge the change
        with repo.createRepoObject().git.custom_environment(
            GIT_SSH_COMMAND=self._get_ssh_cmd(item['connection'])):
            commit = self._mergeChange(item, base)
            if not commit:
                return None
            # Store this commit as the most recent for this project-branch
            recent[key] = commit
            # Set the Zuul ref for this item to point to the most recent
            # commits of each project-branch
            for key, mrc in recent.items():
                connection, project, branch = key
                zuul_ref = None
                try:
                    repo = self.getRepo(connection, project)
                    zuul_ref = branch + '/' + item['ref']
                    if not repo.getCommitFromRef(zuul_ref):
                        repo.createZuulRef(zuul_ref, mrc)
                except Exception:
                    self.log.exception("Unable to set zuul ref %s for "
                                       "item %s" % (zuul_ref, item))
                    return None
            return commit

    def mergeChanges(self, items, files=None, repo_state=None):
        # connection+project+branch -> commit
        recent = {}
        commit = None
        read_files = []
        # connection -> project -> ref -> commit
        if repo_state is None:
            repo_state = {}
        for item in items:
            if item.get("number") and item.get("patchset"):
                self.log.debug("Merging for change %s,%s." %
                               (item["number"], item["patchset"]))
            elif item.get("newrev") and item.get("oldrev"):
                self.log.debug("Merging for rev %s with oldrev %s." %
                               (item["newrev"], item["oldrev"]))
            commit = self._mergeItem(item, recent, repo_state)
            if not commit:
                return None
            if files:
                repo = self.getRepo(item['connection'], item['project'])
                repo_files = repo.getFiles(files, commit=commit)
                read_files.append(dict(
                    connection=item['connection'],
                    project=item['project'],
                    branch=item['branch'],
                    files=repo_files))
        ret_recent = {}
        for k, v in recent.items():
            ret_recent[k] = v.hexsha
        return commit.hexsha, read_files, repo_state, ret_recent

    def getFiles(self, connection_name, project_name, branch, files):
        repo = self.getRepo(connection_name, project_name)
        return repo.getFiles(files, branch=branch)
