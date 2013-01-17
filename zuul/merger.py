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

    def __init__(self, remote, local):
        self.remote_url = remote
        self.local_path = local
        self._ensure_cloned()
        self.repo = git.Repo(self.local_path)

    def _ensure_cloned(self):
        if not os.path.exists(self.local_path):
            self.log.debug("Cloning from %s to %s" % (self.remote_url,
                                                      self.local_path))
            git.Repo.clone_from(self.remote_url, self.local_path)

    def recreateRepoObject(self):
        self.repo = git.Repo(self.local_path)

    def reset(self):
        self.log.debug("Resetting repository %s" % self.local_path)
        self.update()
        origin = self.repo.remotes.origin
        for ref in origin.refs:
            if ref.remote_head == 'HEAD':
                continue
            self.repo.create_head(ref.remote_head, ref, force=True)

        # Reset to remote HEAD (usually origin/master)
        self.repo.head.reference = origin.refs['HEAD']
        self.repo.head.reset(index=True, working_tree=True)
        self.repo.git.clean('-x', '-f', '-d')

    def getBranchHead(self, branch):
        return self.repo.heads[branch]

    def checkout(self, ref):
        self.log.debug("Checking out %s" % ref)
        self.repo.head.reference = ref
        self.repo.head.reset(index=True, working_tree=True)

    def cherryPick(self, ref):
        self.log.debug("Cherry-picking %s" % ref)
        self.fetch(ref)
        self.repo.git.cherry_pick("FETCH_HEAD")

    def merge(self, ref):
        self.log.debug("Merging %s" % ref)
        self.fetch(ref)
        self.repo.git.merge("FETCH_HEAD")

    def fetch(self, ref):
        # The git.remote.fetch method may read in git progress info and
        # interpret it improperly causing an AssertionError. Because the
        # data was fetched properly subsequent fetches don't seem to fail.
        # So try again if an AssertionError is caught.
        origin = self.repo.remotes.origin
        try:
            origin.fetch(ref)
        except AssertionError:
            origin.fetch(ref)

        # If the repository is packed, and we fetch a change that is
        # also entirely packed, the cache may be out of date for the
        # same reason as reset() above.  Avoid these problems by
        # recreating the repo object.
        # https://bugs.launchpad.net/zuul/+bug/1078946
        self.repo = git.Repo(self.local_path)

    def createZuulRef(self, ref, commit='HEAD'):
        self.log.debug("CreateZuulRef %s at %s " % (ref, commit))
        ref = ZuulReference.create(self.repo, ref, commit)
        return ref.commit

    def push(self, local, remote):
        self.log.debug("Pushing %s:%s to %s " % (local, remote,
                                                 self.remote_url))
        self.repo.remotes.origin.push('%s:%s' % (local, remote))

    def update(self):
        self.log.debug("Updating repository %s" % self.local_path)
        origin = self.repo.remotes.origin
        origin.update()
        # If the remote repository is repacked, the repo object's
        # cache may be out of date.  Specifically, it caches whether
        # to check the loose or packed DB for a given SHA.  Further,
        # if there was no pack or lose directory to start with, the
        # repo object may not even have a database for it.  Avoid
        # these problems by recreating the repo object.
        self.repo = git.Repo(self.local_path)


class Merger(object):
    log = logging.getLogger("zuul.Merger")

    def __init__(self, trigger, working_root, push_refs, sshkey):
        self.trigger = trigger
        self.repos = {}
        self.working_root = working_root
        if not os.path.exists(working_root):
            os.makedirs(working_root)
        self.push_refs = push_refs
        if sshkey:
            self._makeSSHWrapper(sshkey)

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
            repo = Repo(url, path)
            self.repos[project] = repo
        except:
            self.log.exception("Unable to initialize repo for %s" % project)

    def getRepo(self, project):
        r = self.repos.get(project, None)
        r.recreateRepoObject()
        return r

    def _mergeChange(self, change, ref, target_ref, mode):
        repo = self.getRepo(change.project)
        try:
            repo.checkout(ref)
        except:
            self.log.exception("Unable to checkout %s" % ref)
            return False

        try:
            if not mode:
                mode = change.project.merge_mode
            if mode == model.MERGE_IF_NECESSARY:
                repo.merge(change.refspec)
            elif mode == model.CHERRY_PICK:
                repo.cherryPick(change.refspec)
        except:
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

    def mergeChanges(self, changes, target_ref=None, mode=None):
        # Merge shortcuts:
        # if this is the only change just merge it against its branch.
        # elif there are changes ahead of us that are from the same project and
        # branch we can merge against the commit associated with that change
        # instead of going back up the tree.
        #
        # Shortcuts assume some external entity is checking whether or not
        # changes from other projects can merge.
        commit = False
        change = changes[-1]
        sibling_filter = lambda c: (c.project == change.project and
                                    c.branch == change.branch)
        sibling_changes = filter(sibling_filter, changes)
        # Only current change to merge against tip of change.branch
        if len(sibling_changes) == 1:
            repo = self.getRepo(change.project)
            # we need to reset here in order to call getBranchHead
            try:
                repo.reset()
            except:
                self.log.exception("Unable to reset repo %s" % repo)
                return False
            commit = self._mergeChange(change,
                                       repo.getBranchHead(change.branch),
                                       target_ref=target_ref, mode=mode)
        # Sibling changes exist. Merge current change against newest sibling.
        elif (len(sibling_changes) >= 2 and
            sibling_changes[-2].current_build_set.commit):
            last_change = sibling_changes[-2].current_build_set.commit
            commit = self._mergeChange(change, last_change,
                                       target_ref=target_ref, mode=mode)
        # Either change did not merge or we did not need to merge as there were
        # previous merge conflicts.
        if not commit:
            return commit

        project_branches = []
        for c in reversed(changes):
            # Here we create all of the necessary zuul refs and potentially
            # push them back to Gerrit.
            if (c.project, c.branch) in project_branches:
                continue
            repo = self.getRepo(c.project)
            if c.project != change.project or c.branch != change.branch:
                # Create a zuul ref for all dependent changes project
                # branch combinations as this is the ref that jenkins will
                # use to test. The ref for change has already been set so
                # we skip it here.
                try:
                    zuul_ref = c.branch + '/' + target_ref
                    repo.createZuulRef(zuul_ref, c.current_build_set.commit)
                except:
                    self.log.exception("Unable to set zuul ref %s for "
                                       "change %s" % (zuul_ref, c))
                    return False
            if self.push_refs:
                # Push the results upstream to the zuul ref after
                # they are created.
                ref = 'refs/zuul/' + c.branch + '/' + target_ref
                try:
                    repo.push(ref, ref)
                    complete = self.trigger.waitForRefSha(c.project, ref)
                except:
                    self.log.exception("Unable to push %s" % ref)
                    return False
                if not complete:
                    self.log.error("Ref %s did not show up in repo" % ref)
                    return False
            project_branches.append((c.project, c.branch))

        return commit
