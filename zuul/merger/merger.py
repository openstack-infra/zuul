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
import os
import logging

import zuul.model


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
        repo_is_cloned = os.path.exists(self.local_path)
        if self._initialized and repo_is_cloned:
            return
        # If the repo does not exist, clone the repo.
        if not repo_is_cloned:
            self.log.debug("Cloning from %s to %s" % (self.remote_url,
                                                      self.local_path))
            git.Repo.clone_from(self.remote_url, self.local_path)
        repo = git.Repo(self.local_path)
        if self.email:
            repo.config_writer().set_value('user', 'email',
                                           self.email)
        if self.username:
            repo.config_writer().set_value('user', 'name',
                                           self.username)
        repo.config_writer().write()
        self._initialized = True

    def isInitialized(self):
        return self._initialized

    def createRepoObject(self):
        try:
            self._ensure_cloned()
            repo = git.Repo(self.local_path)
        except:
            self.log.exception("Unable to initialize repo for %s" %
                               self.local_path)
        return repo

    def reset(self):
        repo = self.createRepoObject()
        self.log.debug("Resetting repository %s" % self.local_path)
        self.update()
        origin = repo.remotes.origin
        for ref in origin.refs:
            if ref.remote_head == 'HEAD':
                continue
            repo.create_head(ref.remote_head, ref, force=True)

        # Reset to remote HEAD (usually origin/master)
        repo.head.reference = origin.refs['HEAD']
        repo.head.reset(index=True, working_tree=True)
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

    def checkout(self, ref):
        repo = self.createRepoObject()
        self.log.debug("Checking out %s" % ref)
        repo.head.reference = ref
        repo.head.reset(index=True, working_tree=True)

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
        self.log.debug("CreateZuulRef %s at %s" % (ref, commit))
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
        origin.update()


class Merger(object):
    log = logging.getLogger("zuul.Merger")

    def __init__(self, working_root, sshkey, email, username):
        self.repos = {}
        self.working_root = working_root
        if not os.path.exists(working_root):
            os.makedirs(working_root)
        if sshkey:
            self._makeSSHWrapper(sshkey)
        self.email = email
        self.username = username

    def _makeSSHWrapper(self, key):
        name = os.path.join(self.working_root, '.ssh_wrapper')
        fd = open(name, 'w')
        fd.write('#!/bin/bash\n')
        fd.write('ssh -i %s $@\n' % key)
        fd.close()
        os.chmod(name, 0755)
        os.environ['GIT_SSH'] = name

    def addProject(self, project, url):
        repo = None
        try:
            path = os.path.join(self.working_root, project)
            repo = Repo(url, path, self.email, self.username)

            self.repos[project] = repo
        except Exception:
            self.log.exception("Unable to add project %s" % project)
        return repo

    def getRepo(self, project, url):
        if project in self.repos:
            return self.repos[project]
        if not url:
            raise Exception("Unable to set up repo for project %s"
                            " without a url" % (project,))
        return self.addProject(project, url)

    def updateRepo(self, project, url):
        repo = self.getRepo(project, url)
        try:
            self.log.info("Updating local repository %s", project)
            repo.update()
        except Exception:
            self.log.exception("Unable to update %s", project)

    def _mergeChange(self, item, ref):
        repo = self.getRepo(item['project'], item['url'])
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

    def _mergeItem(self, item, recent):
        self.log.debug("Processing refspec %s for project %s / %s ref %s" %
                       (item['refspec'], item['project'], item['branch'],
                        item['ref']))
        repo = self.getRepo(item['project'], item['url'])
        key = (item['project'], item['branch'])
        # See if we have a commit for this change already in this repo
        zuul_ref = item['branch'] + '/' + item['ref']
        commit = repo.getCommitFromRef(zuul_ref)
        if commit:
            self.log.debug("Found commit %s for ref %s" % (commit, zuul_ref))
            # Store this as the most recent commit for this
            # project-branch
            recent[key] = commit
            return commit
        self.log.debug("Unable to find commit for ref %s" % (zuul_ref,))
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
            base = repo.getBranchHead(item['branch'])
        else:
            self.log.debug("Found base commit %s for %s" % (base, key,))
        # Merge the change
        commit = self._mergeChange(item, base)
        if not commit:
            return None
        # Store this commit as the most recent for this project-branch
        recent[key] = commit
        # Set the Zuul ref for this item to point to the most recent
        # commits of each project-branch
        for key, mrc in recent.items():
            project, branch = key
            try:
                repo = self.getRepo(project, None)
                zuul_ref = branch + '/' + item['ref']
                repo.createZuulRef(zuul_ref, mrc)
            except Exception:
                self.log.exception("Unable to set zuul ref %s for "
                                   "item %s" % (zuul_ref, item))
                return None
        return commit

    def mergeChanges(self, items):
        recent = {}
        commit = None
        for item in items:
            if item.get("number") and item.get("patchset"):
                self.log.debug("Merging for change %s,%s." %
                               (item["number"], item["patchset"]))
            elif item.get("newrev") and item.get("oldrev"):
                self.log.debug("Merging for rev %s with oldrev %s." %
                               (item["newrev"], item["oldrev"]))
            commit = self._mergeItem(item, recent)
            if not commit:
                return None
        return commit.hexsha
