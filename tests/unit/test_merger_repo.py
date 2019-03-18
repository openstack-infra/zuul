# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import datetime
import logging
import os

import git
import testtools

from zuul.merger.merger import Repo
from zuul.model import MERGER_MERGE_RESOLVE
from tests.base import ZuulTestCase, FIXTURE_DIR, simple_layout


class TestMergerRepo(ZuulTestCase):

    log = logging.getLogger("zuul.test.merger.repo")
    tenant_config_file = 'config/single-tenant/main.yaml'
    workspace_root = None

    def setUp(self):
        super(TestMergerRepo, self).setUp()
        self.workspace_root = os.path.join(self.test_root, 'workspace')

    def test_ensure_cloned(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')

        # Forge a repo having a submodule
        parent_repo = git.Repo(parent_path)
        parent_repo.git.submodule('add', os.path.join(
            self.upstream_root, 'org/project2'), 'subdir')
        parent_repo.index.commit('Adding project2 as a submodule in subdir')
        # git 1.7.8 changed .git from being a directory to a file pointing
        # to the parent repository /.git/modules/*
        self.assertTrue(os.path.exists(
            os.path.join(parent_path, 'subdir', '.git')),
            msg='.git file in submodule should be a file')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        self.assertTrue(
            os.path.isdir(os.path.join(self.workspace_root, 'subdir')),
            msg='Cloned repository has a submodule placeholder directory')
        self.assertFalse(os.path.exists(
            os.path.join(self.workspace_root, 'subdir', '.git')),
            msg='Submodule is not initialized')

        sub_repo = Repo(
            os.path.join(self.upstream_root, 'org/project2'),
            os.path.join(self.workspace_root, 'subdir'),
            'none@example.org', 'User Name', '0', '0')
        self.assertTrue(os.path.exists(
            os.path.join(self.workspace_root, 'subdir', '.git')),
            msg='Cloned over the submodule placeholder')

        self.assertEqual(
            os.path.join(self.upstream_root, 'org/project1'),
            work_repo.createRepoObject().remotes[0].url,
            message="Parent clone still point to upstream project1")

        self.assertEqual(
            os.path.join(self.upstream_root, 'org/project2'),
            sub_repo.createRepoObject().remotes[0].url,
            message="Sub repository points to upstream project2")

    def test_set_refs(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        remote_sha = self.create_commit('org/project1')
        self.create_branch('org/project1', 'foobar')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        repo = git.Repo(self.workspace_root)
        new_sha = repo.heads.foobar.commit.hexsha

        work_repo.setRefs({'refs/heads/master': new_sha}, True)
        self.assertEqual(work_repo.getBranchHead('master').hexsha, new_sha)
        self.assertIn('master', repo.remotes.origin.refs)

        work_repo.setRefs({'refs/heads/master': remote_sha})
        self.assertEqual(work_repo.getBranchHead('master').hexsha, remote_sha)
        self.assertNotIn('master', repo.remotes.origin.refs)

    def test_set_remote_ref(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        commit_sha = self.create_commit('org/project1')
        self.create_commit('org/project1')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        work_repo.setRemoteRef('master', commit_sha)
        work_repo.setRemoteRef('invalid', commit_sha)

        repo = git.Repo(self.workspace_root)
        self.assertEqual(repo.remotes.origin.refs.master.commit.hexsha,
                         commit_sha)
        self.assertNotIn('invalid', repo.remotes.origin.refs)

    def test_clone_timeout(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'fake_git.sh'))
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         git_timeout=0.001, retry_attempts=1)
        # TODO: have the merger and repo classes catch fewer
        # exceptions, including this one on initialization.  For the
        # test, we try cloning again.
        with testtools.ExpectedException(git.exc.GitCommandError,
                                         r'.*exit code\(-9\)'):
            work_repo._ensure_cloned()

    def test_fetch_timeout(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         retry_attempts=1)
        work_repo.git_timeout = 0.001
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'fake_git.sh'))
        with testtools.ExpectedException(git.exc.GitCommandError,
                                         r'.*exit code\(-9\)'):
            work_repo.update()

    def test_fetch_retry(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         retry_interval=1)
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'git_fetch_error.sh'))
        work_repo.update()
        # This is created on the first fetch
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_root, 'stamp1')))
        # This is created on the second fetch
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_root, 'stamp2')))

    def test_deleted_local_ref(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        self.create_branch('org/project1', 'foobar')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')

        # Delete local ref on the cached repo. This leaves us with a remote
        # ref but no local ref anymore.
        gitrepo = git.Repo(work_repo.local_path)
        gitrepo.delete_head('foobar', force=True)

        # Delete the branch upstream.
        self.delete_branch('org/project1', 'foobar')

        # And now reset the repo again. This should not crash
        work_repo.reset()

    def test_broken_cache(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        self.waitUntilSettled()

        # Break the work repo
        path = work_repo.local_path
        os.remove(os.path.join(path, '.git/HEAD'))

        # And now reset the repo again. This should not crash
        work_repo.reset()

        # Now open a cache repo and break it in a way that git.Repo is happy
        # at first but git won't be.
        merger = self.executor_server.merger
        cache_repo = merger.getRepo('gerrit', 'org/project')
        with open(os.path.join(cache_repo.local_path, '.git/HEAD'), 'w'):
            pass
        cache_repo.update()

    def test_broken_gitmodules(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        self.waitUntilSettled()

        # Break the gitmodules
        path = work_repo.local_path
        with open(os.path.join(path, '.gitmodules'), 'w') as f:
            f.write('[submodule "libfoo"]\n'
                    'path = include/foo\n'
                    '---\n'
                    'url = git://example.com/git/lib.git')

        # And now reset the repo again. This should not crash
        work_repo.reset()

    def test_files_changes(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        self.create_branch('org/project1', 'feature')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        changed_files = work_repo.getFilesChanges('feature', 'master')

        self.assertEqual(['README'], changed_files)

    def test_files_changes_master_fork_merges(self):
        """Regression test for getFilesChanges()

        Check if correct list of changed files is listed for a messy
        branch that has a merge of a fork, with the fork including a
        merge of a new master revision.

        The previously used "git merge-base" approach did not handle this
        case correctly.
        """
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        repo = git.Repo(parent_path)

        self.create_branch('org/project1', 'messy',
                           commit_filename='messy1.txt')

        # Let time pass to reproduce the order for this error case
        commit_date = datetime.datetime.now() + datetime.timedelta(seconds=5)
        commit_date = commit_date.replace(microsecond=0).isoformat()

        # Create a commit on 'master' so we can merge it into the fork
        files = {"master.txt": "master"}
        master_ref = self.create_commit('org/project1', files=files,
                                        message="Add master.txt",
                                        commit_date=commit_date)
        repo.refs.master.commit = master_ref

        # Create a fork of the 'messy' branch and merge
        # 'master' into the fork (no fast-forward)
        repo.create_head("messy-fork")
        repo.heads["messy-fork"].commit = "messy"
        repo.head.reference = 'messy'
        repo.head.reset(index=True, working_tree=True)
        repo.git.checkout('messy-fork')
        repo.git.merge('master', no_ff=True)

        # Merge fork back into 'messy' branch (no fast-forward)
        repo.head.reference = 'messy'
        repo.head.reset(index=True, working_tree=True)
        repo.git.checkout('messy')
        repo.git.merge('messy-fork', no_ff=True)

        # Create another commit on top of 'messy'
        files = {"messy2.txt": "messy2"}
        messy_ref = self.create_commit('org/project1', files=files,
                                       head='messy', message="Add messy2.txt")
        repo.refs.messy.commit = messy_ref

        # Check that we get all changes for the 'messy' but not 'master' branch
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        changed_files = work_repo.getFilesChanges('messy', 'master')
        self.assertEqual(sorted(['messy1.txt', 'messy2.txt']),
                         sorted(changed_files))


class TestMergerWithAuthUrl(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'

    git_url_with_auth = True

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_changing_url(self):
        """
        This test checks that if getGitUrl returns different urls for the same
        repo (which happens if an access token is part of the url) then the
        remote urls are changed in the merger accordingly. This tests directly
        the merger.
        """

        merger = self.executor_server.merger
        repo = merger.getRepo('github', 'org/project')
        first_url = repo.remote_url

        repo = merger.getRepo('github', 'org/project')
        second_url = repo.remote_url

        # the urls should differ
        self.assertNotEqual(first_url, second_url)

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_changing_url_end_to_end(self):
        """
        This test checks that if getGitUrl returns different urls for the same
        repo (which happens if an access token is part of the url) then the
        remote urls are changed in the merger accordingly. This is an end to
        end test.
        """

        A = self.fake_github.openFakePullRequest('org/project', 'master',
                                                 'PR title')
        self.fake_github.emitEvent(A.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)

        # get remote url of org/project in merger
        repo = self.executor_server.merger.repos.get('github.com/org/project')
        self.assertIsNotNone(repo)
        git_repo = git.Repo(repo.local_path)
        first_url = list(git_repo.remotes[0].urls)[0]

        B = self.fake_github.openFakePullRequest('org/project', 'master',
                                                 'PR title')
        self.fake_github.emitEvent(B.getCommentAddedEvent('merge me again'))
        self.waitUntilSettled()
        self.assertTrue(B.is_merged)

        repo = self.executor_server.merger.repos.get('github.com/org/project')
        self.assertIsNotNone(repo)
        git_repo = git.Repo(repo.local_path)
        second_url = list(git_repo.remotes[0].urls)[0]

        # the urls should differ
        self.assertNotEqual(first_url, second_url)


class TestMerger(ZuulTestCase):

    tenant_config_file = 'config/single-tenant/main.yaml'

    @staticmethod
    def _item_from_fake_change(fake_change):
        return dict(
            number=fake_change.number,
            patchset=1,
            ref=fake_change.patchsets[0]['ref'],
            connection='gerrit',
            branch=fake_change.branch,
            project=fake_change.project,
            buildset_uuid='fake-uuid',
            merge_mode=MERGER_MERGE_RESOLVE,
        )

    def test_merge_multiple_items(self):
        """
        Tests that the merger merges and returns the requested file changes per
        change and in the correct order.
        """

        merger = self.executor_server.merger
        files = ['zuul.yaml', '.zuul.yaml']
        dirs = ['zuul.d', '.zuul.d']

        # Simple change A
        file_dict_a = {'zuul.d/a.yaml': 'a'}
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A',
                                           files=file_dict_a)
        item_a = self._item_from_fake_change(A)

        # Simple change B
        file_dict_b = {'zuul.d/b.yaml': 'b'}
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'B',
                                           files=file_dict_b)
        item_b = self._item_from_fake_change(B)

        # Simple change C on top of A
        file_dict_c = {'zuul.d/a.yaml': 'a-with-c'}
        C = self.fake_gerrit.addFakeChange('org/project', 'master', 'C',
                                           files=file_dict_c,
                                           parent=A.patchsets[0]['ref'])
        item_c = self._item_from_fake_change(C)

        # Change in different project
        file_dict_d = {'zuul.d/a.yaml': 'a-in-project1'}
        D = self.fake_gerrit.addFakeChange('org/project1', 'master', 'D',
                                           files=file_dict_d)
        item_d = self._item_from_fake_change(D)

        # Merge A
        result = merger.mergeChanges([item_a], files=files, dirs=dirs)
        self.assertIsNotNone(result)
        hexsha, read_files, repo_state, ret_recent, orig_commit = result
        self.assertEqual(len(read_files), 1)
        self.assertEqual(read_files[0]['project'], 'org/project')
        self.assertEqual(read_files[0]['branch'], 'master')
        self.assertEqual(read_files[0]['files']['zuul.d/a.yaml'], 'a')

        # Merge A -> B
        result = merger.mergeChanges([item_a, item_b], files=files, dirs=dirs)
        self.assertIsNotNone(result)
        hexsha, read_files, repo_state, ret_recent, orig_commit = result
        self.assertEqual(len(read_files), 2)
        self.assertEqual(read_files[0]['project'], 'org/project')
        self.assertEqual(read_files[0]['branch'], 'master')
        self.assertEqual(read_files[0]['files']['zuul.d/a.yaml'], 'a')
        self.assertEqual(read_files[1]['project'], 'org/project')
        self.assertEqual(read_files[1]['branch'], 'master')
        self.assertEqual(read_files[1]['files']['zuul.d/b.yaml'], 'b')

        # Merge A -> B -> C
        result = merger.mergeChanges([item_a, item_b, item_c], files=files,
                                     dirs=dirs)
        self.assertIsNotNone(result)
        hexsha, read_files, repo_state, ret_recent, orig_commit = result
        self.assertEqual(len(read_files), 3)
        self.assertEqual(read_files[0]['project'], 'org/project')
        self.assertEqual(read_files[0]['branch'], 'master')
        self.assertEqual(read_files[0]['files']['zuul.d/a.yaml'], 'a')
        self.assertEqual(read_files[1]['project'], 'org/project')
        self.assertEqual(read_files[1]['branch'], 'master')
        self.assertEqual(read_files[1]['files']['zuul.d/b.yaml'], 'b')
        self.assertEqual(read_files[2]['project'], 'org/project')
        self.assertEqual(read_files[2]['branch'], 'master')
        self.assertEqual(read_files[2]['files']['zuul.d/a.yaml'],
                         'a-with-c')

        # Merge A -> B -> C -> D
        result = merger.mergeChanges([item_a, item_b, item_c, item_d],
                                     files=files, dirs=dirs)
        self.assertIsNotNone(result)
        hexsha, read_files, repo_state, ret_recent, orig_commit = result

        self.assertEqual(len(read_files), 4)
        self.assertEqual(read_files[0]['project'], 'org/project')
        self.assertEqual(read_files[0]['branch'], 'master')
        self.assertEqual(read_files[0]['files']['zuul.d/a.yaml'], 'a')
        self.assertEqual(read_files[1]['project'], 'org/project')
        self.assertEqual(read_files[1]['branch'], 'master')
        self.assertEqual(read_files[1]['files']['zuul.d/b.yaml'], 'b')
        self.assertEqual(read_files[2]['project'], 'org/project')
        self.assertEqual(read_files[2]['branch'], 'master')
        self.assertEqual(read_files[2]['files']['zuul.d/a.yaml'],
                         'a-with-c')
        self.assertEqual(read_files[3]['project'], 'org/project1')
        self.assertEqual(read_files[3]['branch'], 'master')
        self.assertEqual(read_files[3]['files']['zuul.d/a.yaml'],
                         'a-in-project1')
