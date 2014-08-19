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
import yaml

from git import GitCommandError
from zuul.lib.clonemapper import CloneMapper
from zuul.merger.merger import Repo


class Cloner(object):
    log = logging.getLogger("zuul.Cloner")

    def __init__(self, git_base_url, projects, workspace, zuul_branch,
                 zuul_ref, zuul_url, branch=None, clone_map_file=None,
                 project_branches=None, cache_dir=None):

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
        self.project_branches = project_branches or {}

        if clone_map_file:
            self.readCloneMap(clone_map_file)

    def readCloneMap(self, clone_map_file):
        clone_map_file = os.path.expanduser(clone_map_file)
        if not os.path.exists(clone_map_file):
            raise Exception("Unable to read clone map file at %s." %
                            clone_map_file)
        clone_map_file = open(clone_map_file)
        self.clone_map = yaml.load(clone_map_file).get('clonemap')
        self.log.info("Loaded map containing %s rules", len(self.clone_map))
        return self.clone_map

    def execute(self):
        mapper = CloneMapper(self.clone_map, self.projects)
        dests = mapper.expand(workspace=self.workspace)

        self.log.info("Preparing %s repositories", len(dests))
        for project, dest in dests.iteritems():
            self.prepareRepo(project, dest)
        self.log.info("Prepared all repositories")

    def cloneUpstream(self, project, dest):
        # Check for a cached git repo first
        git_cache = '%s/%s' % (self.cache_dir, project)
        git_upstream = '%s/%s' % (self.git_url, project)
        if (self.cache_dir and
            os.path.exists(git_cache) and
            not os.path.exists(dest)):
            # file:// tells git not to hard-link across repos
            git_cache = 'file://%s' % git_cache
            self.log.info("Creating repo %s from cache %s",
                          project, git_cache)
            new_repo = git.Repo.clone_from(git_cache, dest)
            self.log.info("Updating origin remote in repo %s to %s",
                          project, git_upstream)
            new_repo.remotes.origin.config_writer.set('url', git_upstream)
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

    def fetchFromZuul(self, repo, project, ref):
        zuul_remote = '%s/%s' % (self.zuul_url, project)

        try:
            repo.fetchFrom(zuul_remote, ref)
            self.log.debug("Fetched ref %s from %s", ref, project)
            return True
        except (ValueError, GitCommandError):
            self.log.debug("Project %s in Zuul does not have ref %s",
                           project, ref)
            return False

    def prepareRepo(self, project, dest):
        """Clone a repository for project at dest and apply a reference
        suitable for testing. The reference lookup is attempted in this order:

         1) Zuul reference for the indicated branch
         2) Zuul reference for the master branch
         3) The tip of the indicated branch
         4) The tip of the master branch

        The "indicated branch" is one of the following:

         A) The project-specific override branch (from project_branches arg)
         B) The user specified branch (from the branch arg)
         C) ZUUL_BRANCH (from the zuul_branch arg)
        """

        repo = self.cloneUpstream(project, dest)

        repo.update()
        # Ensure that we don't have stale remotes around
        repo.prune()

        indicated_branch = self.branch or self.zuul_branch
        if project in self.project_branches:
            indicated_branch = self.project_branches[project]

        override_zuul_ref = re.sub(self.zuul_branch, indicated_branch,
                                   self.zuul_ref)

        if repo.hasBranch(indicated_branch):
            self.log.debug("upstream repo has branch %s", indicated_branch)
            fallback_branch = indicated_branch
        else:
            self.log.debug("upstream repo is missing branch %s",
                           self.branch)
            # FIXME should be origin HEAD branch which might not be 'master'
            fallback_branch = 'master'

        fallback_zuul_ref = re.sub(self.zuul_branch, fallback_branch,
                                   self.zuul_ref)

        if (self.fetchFromZuul(repo, project, override_zuul_ref)
            or (fallback_zuul_ref != override_zuul_ref and
                self.fetchFromZuul(repo, project, fallback_zuul_ref))
            ):
            # Work around a bug in GitPython which can not parse FETCH_HEAD
            gitcmd = git.Git(dest)
            fetch_head = gitcmd.rev_parse('FETCH_HEAD')
            repo.checkout(fetch_head)
            self.log.info("Prepared %s repo with commit %s",
                          project, fetch_head)
        else:
            # Checkout branch
            self.log.debug("Falling back to branch %s", fallback_branch)
            try:
                repo.checkout('remotes/origin/%s' % fallback_branch)
            except (ValueError, GitCommandError):
                self.log.exception("Fallback branch not found: %s",
                                   fallback_branch)
            self.log.info("Prepared %s repo with branch %s",
                          project, fallback_branch)
