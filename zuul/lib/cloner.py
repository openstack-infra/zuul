# Copyright 2014 Antoine "hashar" Musso
# Copyright 2014 Wikimedia Foundation Inc.
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
import logging
import os
import re

from git import GitCommandError
from zuul import exceptions
from zuul.lib.clonemapper import CloneMapper
from zuul.lib import yamlutil as yaml
from zuul.merger.merger import Repo


class Cloner(object):
    log = logging.getLogger("zuul.Cloner")

    def __init__(self, git_base_url, projects, workspace, zuul_branch,
                 zuul_ref, zuul_url, branch=None, clone_map_file=None,
                 project_branches=None, cache_dir=None, zuul_newrev=None,
                 zuul_project=None):

        self.clone_map = []
        self.dests = None

        self.branch = branch
        self.git_url = git_base_url
        self.cache_dir = cache_dir
        self.projects = projects
        self.workspace = workspace
        self.zuul_branch = zuul_branch or ''
        self.zuul_ref = zuul_ref or ''
        self.zuul_url = zuul_url
        self.zuul_project = zuul_project

        self.project_branches = project_branches or {}
        self.project_revisions = {}

        if zuul_newrev and zuul_project:
            self.project_revisions[zuul_project] = zuul_newrev

        if clone_map_file:
            self.readCloneMap(clone_map_file)

    def readCloneMap(self, clone_map_file):
        clone_map_file = os.path.expanduser(clone_map_file)
        if not os.path.exists(clone_map_file):
            raise Exception("Unable to read clone map file at %s." %
                            clone_map_file)
        clone_map_file = open(clone_map_file)
        self.clone_map = yaml.safe_load(clone_map_file).get('clonemap')
        self.log.info("Loaded map containing %s rules", len(self.clone_map))
        return self.clone_map

    def execute(self):
        mapper = CloneMapper(self.clone_map, self.projects)
        dests = mapper.expand(workspace=self.workspace)

        self.log.info("Preparing %s repositories", len(dests))
        for project, dest in dests.items():
            self.prepareRepo(project, dest)
        self.log.info("Prepared all repositories")

    def cloneUpstream(self, project, dest):
        # Check for a cached git repo first
        git_cache = '%s/%s' % (self.cache_dir, project)

        # Then, if we are cloning the repo for the zuul_project, then
        # set its origin to be the zuul merger, as it is guaranteed to
        # be correct and up to date even if mirrors haven't updated
        # yet.  Otherwise, we can not be sure about the state of the
        # project, so our best chance to get the most current state is
        # by setting origin to the git_url.
        if (self.zuul_url and project == self.zuul_project):
            git_upstream = '%s/%s' % (self.zuul_url, project)
        else:
            git_upstream = '%s/%s' % (self.git_url, project)

        repo_is_cloned = os.path.exists(os.path.join(dest, '.git'))
        if (self.cache_dir and
            os.path.exists(git_cache) and
            not repo_is_cloned):
            # file:// tells git not to hard-link across repos
            git_cache = 'file://%s' % git_cache
            self.log.info("Creating repo %s from cache %s",
                          project, git_cache)
            new_repo = git.Repo.clone_from(git_cache, dest)
            self.log.info("Updating origin remote in repo %s to %s",
                          project, git_upstream)
            new_repo.remotes.origin.config_writer.set('url',
                                                      git_upstream).release()
        else:
            self.log.info("Creating repo %s from upstream %s",
                          project, git_upstream)
        repo = Repo(
            remote=git_upstream,
            local=dest,
            email=None,
            username=None)

        if not repo.isInitialized():
            raise Exception("Error cloning %s to %s" % (git_upstream, dest))

        return repo

    def fetchRef(self, repo, project, ref):
        # If we are fetching a zuul ref, the only place to get it is
        # from the zuul merger (and it is guaranteed to be correct).
        # Otherwise, the only way we can be certain that the ref
        # (which, since it is not a zuul ref, is a branch or tag) is
        # correct is in the case that it matches zuul_project.  If
        # neither of those two conditions are met, we are most likely
        # to get the correct state from the git_url.
        if (ref.startswith('refs/zuul') or
            project == self.zuul_project):

            remote = '%s/%s' % (self.zuul_url, project)
        else:
            remote = '%s/%s' % (self.git_url, project)

        try:
            repo.fetchFrom(remote, ref)
            self.log.debug("Fetched ref %s from %s", ref, remote)
            return True
        except ValueError:
            self.log.debug("Repo %s does not have ref %s",
                           remote, ref)
            return False
        except GitCommandError as error:
            # Bail out if fetch fails due to infrastructure reasons
            if error.stderr.startswith('fatal: unable to access'):
                raise
            self.log.debug("Repo %s does not have ref %s",
                           remote, ref)
            return False

    def prepareRepo(self, project, dest):
        """Clone a repository for project at dest and apply a reference
        suitable for testing. The reference lookup is attempted in this order:

         1) The indicated revision for specific project
         2) Zuul reference for the indicated branch
         3) Zuul reference for the master branch
         4) The tip of the indicated branch
         5) The tip of the master branch

        If an "indicated revision" is specified for this project, and we are
        unable to meet this requirement, we stop attempting to check this
        repo out and raise a zuul.exceptions.RevNotFound exception.

        The "indicated branch" is one of the following:

         A) The project-specific override branch (from project_branches arg)
         B) The user specified branch (from the branch arg)
         C) ZUUL_BRANCH (from the zuul_branch arg)
        """

        repo = self.cloneUpstream(project, dest)

        # Ensure that we don't have stale remotes around
        repo.prune()
        # We must reset after pruning because reseting sets HEAD to point
        # at refs/remotes/origin/master, but `git branch` which prune runs
        # explodes if HEAD does not point at something in refs/heads.
        # Later with repo.checkout() we set HEAD to something that
        # `git branch` is happy with.
        repo.reset()

        indicated_revision = None
        if project in self.project_revisions:
            indicated_revision = self.project_revisions[project]

        indicated_branch = self.branch or self.zuul_branch
        if project in self.project_branches:
            indicated_branch = self.project_branches[project]

        if indicated_branch:
            override_zuul_ref = re.sub(self.zuul_branch, indicated_branch,
                                       self.zuul_ref)
        else:
            override_zuul_ref = None

        if indicated_branch and repo.hasBranch(indicated_branch):
            self.log.info("upstream repo has branch %s", indicated_branch)
            fallback_branch = indicated_branch
        else:
            if indicated_branch:
                self.log.info("upstream repo is missing branch %s",
                              indicated_branch)
            # FIXME should be origin HEAD branch which might not be 'master'
            fallback_branch = 'master'

        if self.zuul_branch:
            fallback_zuul_ref = re.sub(self.zuul_branch, fallback_branch,
                                       self.zuul_ref)
        else:
            fallback_zuul_ref = None

        # If the user has requested an explicit revision to be checked out,
        # we use it above all else, and if we cannot satisfy this requirement
        # we raise an error and do not attempt to continue.
        if indicated_revision:
            self.log.info("Attempting to check out revision %s for "
                          "project %s", indicated_revision, project)
            try:
                self.fetchRef(repo, project, self.zuul_ref)
                commit = repo.checkout(indicated_revision)
            except (ValueError, GitCommandError):
                raise exceptions.RevNotFound(project, indicated_revision)
            self.log.info("Prepared '%s' repo at revision '%s'", project,
                          indicated_revision)
        # If we have a non empty zuul_ref to use, use it. Otherwise we fall
        # back to checking out the branch.
        elif ((override_zuul_ref and
              self.fetchRef(repo, project, override_zuul_ref)) or
              (fallback_zuul_ref and
               fallback_zuul_ref != override_zuul_ref and
              self.fetchRef(repo, project, fallback_zuul_ref))):
            # Work around a bug in GitPython which can not parse FETCH_HEAD
            gitcmd = git.Git(dest)
            fetch_head = gitcmd.rev_parse('FETCH_HEAD')
            repo.checkout(fetch_head)
            self.log.info("Prepared %s repo with commit %s",
                          project, fetch_head)
        else:
            # Checkout branch
            self.log.info("Falling back to branch %s", fallback_branch)
            try:
                commit = repo.checkout('remotes/origin/%s' % fallback_branch)
            except (ValueError, GitCommandError):
                self.log.exception("Fallback branch not found: %s",
                                   fallback_branch)
            self.log.info("Prepared %s repo with branch %s at commit %s",
                          project, fallback_branch, commit)
