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

import git
import os
import logging
import model


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

    def getBranchHead(self, branch):
        repo = self.createRepoObject()
        branch_head = repo.heads[branch]
        return branch_head

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

    def merge(self, ref, strategy=None):
        repo = self.createRepoObject()
        args = []
        if strategy:
            args += ['-s', strategy]
        args.append('FETCH_HEAD')
        self.fetch(ref)
        self.log.debug("Merging %s with args %s" % (ref, args))
        repo.git.merge(*args)

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

    def createZuulRef(self, ref, commit='HEAD'):
        repo = self.createRepoObject()
        self.log.debug("CreateZuulRef %s at %s " % (ref, commit))
        ref = ZuulReference.create(repo, ref, commit)
        return ref.commit

    def push(self, local, remote):
        repo = self.createRepoObject()
        self.log.debug("Pushing %s:%s to %s " % (local, remote,
                                                 self.remote_url))
        repo.remotes.origin.push('%s:%s' % (local, remote))

    def update(self):
        repo = self.createRepoObject()
        self.log.debug("Updating repository %s" % self.local_path)
        origin = repo.remotes.origin
        origin.update()


class Merger(object):
    log = logging.getLogger("zuul.Merger")

    def __init__(self, trigger, working_root, push_refs, sshkey, email,
                 username):
        self.trigger = trigger
        self.repos = {}
        self.working_root = working_root
        if not os.path.exists(working_root):
            os.makedirs(working_root)
        self.push_refs = push_refs
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
        try:
            path = os.path.join(self.working_root, project.name)
            repo = Repo(url, path, self.email, self.username)

            self.repos[project] = repo
        except:
            self.log.exception("Unable to add project %s" % project)

    def getRepo(self, project):
        return self.repos.get(project, None)

    def updateRepo(self, project):
        repo = self.getRepo(project)
        try:
            self.log.info("Updating local repository %s", project)
            repo.update()
        except:
            self.log.exception("Unable to update %s", project)

    def _mergeChange(self, change, ref, target_ref):
        repo = self.getRepo(change.project)
        try:
            repo.checkout(ref)
        except:
            self.log.exception("Unable to checkout %s" % ref)
            return False

        try:
            mode = change.project.merge_mode
            if mode == model.MERGER_MERGE:
                repo.merge(change.refspec)
            elif mode == model.MERGER_MERGE_RESOLVE:
                repo.merge(change.refspec, 'resolve')
            elif mode == model.MERGER_CHERRY_PICK:
                repo.cherryPick(change.refspec)
            else:
                raise Exception("Unsupported merge mode: %s" % mode)
        except Exception:
            # Log exceptions at debug level because they are
            # usually benign merge conflicts
            self.log.debug("Unable to merge %s" % change, exc_info=True)
            return False

        try:
            # Keep track of the last commit, it's the commit that
            # will be passed to jenkins because it's the commit
            # for the triggering change
            zuul_ref = change.branch + '/' + target_ref
            commit = repo.createZuulRef(zuul_ref, 'HEAD').hexsha
        except:
            self.log.exception("Unable to set zuul ref %s for change %s" %
                               (zuul_ref, change))
            return False
        return commit

    def mergeChanges(self, items, target_ref=None):
        # Merge shortcuts:
        # if this is the only change just merge it against its branch.
        # elif there are changes ahead of us that are from the same project and
        # branch we can merge against the commit associated with that change
        # instead of going back up the tree.
        #
        # Shortcuts assume some external entity is checking whether or not
        # changes from other projects can merge.
        commit = False
        item = items[-1]
        sibling_filter = lambda i: (i.change.project == item.change.project and
                                    i.change.branch == item.change.branch)
        sibling_items = filter(sibling_filter, items)
        # Only current change to merge against tip of change.branch
        if len(sibling_items) == 1:
            repo = self.getRepo(item.change.project)
            # we need to reset here in order to call getBranchHead
            try:
                repo.reset()
            except:
                self.log.exception("Unable to reset repo %s" % repo)
                return False
            commit = self._mergeChange(item.change,
                                       repo.getBranchHead(item.change.branch),
                                       target_ref=target_ref)
        # Sibling changes exist. Merge current change against newest sibling.
        elif (len(sibling_items) >= 2 and
              sibling_items[-2].current_build_set.commit):
            last_commit = sibling_items[-2].current_build_set.commit
            commit = self._mergeChange(item.change, last_commit,
                                       target_ref=target_ref)
        # Either change did not merge or we did not need to merge as there were
        # previous merge conflicts.
        if not commit:
            return commit

        project_branches = []
        for i in reversed(items):
            # Here we create all of the necessary zuul refs and potentially
            # push them back to Gerrit.
            if (i.change.project, i.change.branch) in project_branches:
                continue
            repo = self.getRepo(i.change.project)
            if (i.change.project != item.change.project or
                i.change.branch != item.change.branch):
                # Create a zuul ref for all dependent changes project
                # branch combinations as this is the ref that jenkins will
                # use to test. The ref for change has already been set so
                # we skip it here.
                try:
                    zuul_ref = i.change.branch + '/' + target_ref
                    repo.createZuulRef(zuul_ref, i.current_build_set.commit)
                except:
                    self.log.exception("Unable to set zuul ref %s for "
                                       "change %s" % (zuul_ref, i.change))
                    return False
            if self.push_refs:
                # Push the results upstream to the zuul ref after
                # they are created.
                ref = 'refs/zuul/' + i.change.branch + '/' + target_ref
                try:
                    repo.push(ref, ref)
                    complete = self.trigger.waitForRefSha(i.change.project,
                                                          ref)
                except:
                    self.log.exception("Unable to push %s" % ref)
                    return False
                if not complete:
                    self.log.error("Ref %s did not show up in repo" % ref)
                    return False
            project_branches.append((i.change.project, i.change.branch))

        return commit
