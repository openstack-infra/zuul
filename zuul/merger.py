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
            # Pick up any tags or branch updates since we last ran:
            self.update()
        except:
            self.log.exception("Unable to initialize repo for %s" % remote)

    def _ensure_cloned(self):
        if self._initialized:
            return
        if not os.path.exists(self.local_path):
            self.log.debug("Cloning from %s to %s" % (self.remote_url,
                                                      self.local_path))
            git.Repo.clone_from(self.remote_url, self.local_path)
        self.repo = git.Repo(self.local_path)
        if self.email:
            self.repo.config_writer().set_value('user', 'email',
                                                self.email)
        if self.username:
            self.repo.config_writer().set_value('user', 'name',
                                                self.username)
        self.repo.config_writer().write()
        self._initialized = True

    def recreateRepoObject(self):
        self._ensure_cloned()
        self.repo = git.Repo(self.local_path)

    def checkout(self, ref):
        self._ensure_cloned()
        self.log.debug("Checking out %s" % ref)
        self.repo.head.reset(index=True, working_tree=True)
        self.repo.git.clean('-x', '-f', '-d')
        if self.repo.re_hexsha_only.match(ref):
            self.repo.git.checkout(ref)
        else:
            self.fetch(ref)
            self.repo.git.checkout("FETCH_HEAD")

    def cherryPick(self, ref):
        self._ensure_cloned()
        self.log.debug("Cherry-picking %s" % ref)
        self.fetch(ref)
        self.repo.git.cherry_pick("FETCH_HEAD")

    def merge(self, ref, strategy=None):
        self._ensure_cloned()
        args = []
        if strategy:
            args += ['-s', strategy]
        args.append('FETCH_HEAD')
        self.fetch(ref)
        self.log.debug("Merging %s with args %s" % (ref, args))
        self.repo.git.merge(*args)

    def fetch(self, ref):
        self._ensure_cloned()
        # The git.remote.fetch method may read in git progress info and
        # interpret it improperly causing an AssertionError. Because the
        # data was fetched properly subsequent fetches don't seem to fail.
        # So try again if an AssertionError is caught.
        origin = self.repo.remotes.origin
        self.log.debug("Fetching %s" % ref)
        try:
            origin.fetch(ref)
        except AssertionError:
            origin.fetch(ref)

        # If the repository is packed, and we fetch a change that is
        # also entirely packed, the cache may be out of date.
        # See the comment in update() and
        # https://bugs.launchpad.net/zuul/+bug/1078946
        self.repo = git.Repo(self.local_path)

    def createZuulRef(self, ref, commit='HEAD'):
        self._ensure_cloned()
        self.log.debug("CreateZuulRef %s at %s " % (ref, commit))
        ref = ZuulReference.create(self.repo, ref, commit)
        return ref.commit

    def push(self, local, remote):
        self._ensure_cloned()
        self.log.debug("Pushing %s:%s to %s " % (local, remote,
                                                 self.remote_url))
        self.repo.remotes.origin.push('%s:%s' % (local, remote))

    def update(self):
        self._ensure_cloned()
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
        r = self.repos.get(project, None)
        r.recreateRepoObject()
        return r

    def updateRepo(self, project, ref=None):
        repo = self.getRepo(project)
        try:
            if ref:
                self.log.debug("Fetching ref %s for local repository %s" %
                               (ref, project))
                repo.fetch(ref)
            else:
                self.log.info("Updating local repository %s" % project)
                repo.update()
        except:
            self.log.exception("Unable to update %s" % project)

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
            commit = self._mergeChange(item.change,
                                       item.change.branch,
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
