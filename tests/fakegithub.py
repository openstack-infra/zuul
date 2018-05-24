#!/usr/bin/env python

# Copyright 2018 Red Hat, Inc.
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

import re

FAKE_BASE_URL = 'https://example.com/api/v3/'


class FakeUser(object):
    def __init__(self, login):
        self.login = login
        self.name = "Github User"
        self.email = "github.user@example.com"


class FakeBranch(object):
    def __init__(self, branch='master'):
        self.name = branch


class FakeStatus(object):
    def __init__(self, state, url, description, context, user):
        self.state = state
        self.context = context
        self._url = url
        self._description = description
        self._user = user

    def as_dict(self):
        return {
            'state': self.state,
            'url': self._url,
            'description': self._description,
            'context': self.context,
            'creator': {
                'login': self._user
            }
        }


class FakeCommit(object):
    def __init__(self, sha):
        self._statuses = []
        self.sha = sha

    def set_status(self, state, url, description, context, user):
        status = FakeStatus(
            state, url, description, context, user)
        # always insert a status to the front of the list, to represent
        # the last status provided for a commit.
        self._statuses.insert(0, status)

    def statuses(self):
        return self._statuses


class FakeRepository(object):
    def __init__(self, name, data):
        self._api = FAKE_BASE_URL
        self._branches = [FakeBranch()]
        self._commits = {}
        self.data = data
        self.name = name

    def branches(self, protected=False):
        if protected:
            # simulate there is no protected branch
            return []
        return self._branches

    def _build_url(self, *args, **kwargs):
        path_args = ['repos', self.name]
        path_args.extend(args)
        fakepath = '/'.join(path_args)
        return FAKE_BASE_URL + fakepath

    def _get(self, url, headers=None):
        client = FakeGithubClient(self.data)
        return client.session.get(url, headers)

    def create_status(self, sha, state, url, description, context,
                      user='zuul'):
        # Since we're bypassing github API, which would require a user, we
        # default the user as 'zuul' here.
        commit = self._commits.get(sha, None)
        if commit is None:
            commit = FakeCommit(sha)
            self._commits[sha] = commit
        commit.set_status(state, url, description, context, user)

    def commit(self, sha):
        commit = self._commits.get(sha, None)
        if commit is None:
            commit = FakeCommit(sha)
            self._commits[sha] = commit
        return commit

    def get_url(self, path):
        entity, request = path.split('/', 1)

        if entity == 'branches':
            return self.get_url_branch(request)
        if entity == 'collaborators':
            return self.get_url_collaborators(request)
        else:
            return None

    def get_url_branch(self, path):
        branch, entity = path.split('/')

        if entity == 'protection':
            return self.get_url_protection(branch)
        else:
            return None

    def get_url_collaborators(self, path):
        login, entity = path.split('/')

        if entity == 'permission':
            owner, proj = self.name.split('/')
            permission = None
            for pr in self.data.pull_requests.values():
                pr_owner, pr_project = pr.project.split('/')
                if (pr_owner == owner and proj == pr_project):
                    if login in pr.admins:
                        permission = 'admin'
                        break
                    elif login in pr.writers:
                        permission = 'write'
                        break
                    else:
                        permission = 'read'
            data = {
                'permission': permission,
            }
            return FakeResponse(data)
        else:
            return None

    def get_url_protection(self, branch):
        contexts = self.data.required_contexts.get((self.name, branch), [])
        data = {
            'required_status_checks': {
                'contexts': contexts
            }
        }
        return FakeResponse(data)

    def pull_requests(self, state=None):
        pulls = []
        for pull in self.data.pull_requests.values():
            if pull.project != self.name:
                continue
            if state and pull.state != state:
                continue
            pulls.append(FakePull(pull))
        return pulls


class FakeLabel(object):
    def __init__(self, name):
        self.name = name


class FakeIssue(object):
    def __init__(self, fake_pull_request):
        self._fake_pull_request = fake_pull_request

    def pull_request(self):
        return FakePull(self._fake_pull_request)

    def labels(self):
        return [FakeLabel(l)
                for l in self._fake_pull_request.labels]


class FakeFile(object):
    def __init__(self, filename):
        self.filename = filename


class FakePull(object):
    def __init__(self, fake_pull_request):
        self._fake_pull_request = fake_pull_request

    def issue(self):
        return FakeIssue(self._fake_pull_request)

    def files(self):
        return [FakeFile(fn)
                for fn in self._fake_pull_request.files]

    @property
    def head(self):
        client = FakeGithubClient(self._fake_pull_request.github.github_data)
        repo = client.repo_from_project(self._fake_pull_request.project)
        return repo.commit(self._fake_pull_request.head_sha)

    def commits(self):
        # since we don't know all commits of a pr we just return here a list
        # with the head_sha as the only commit
        return [self.head]

    def as_dict(self):
        pr = self._fake_pull_request
        connection = pr.github
        data = {
            'number': pr.number,
            'title': pr.subject,
            'url': 'https://%s/%s/pull/%s' % (
                connection.server, pr.project, pr.number
            ),
            'updated_at': pr.updated_at,
            'base': {
                'repo': {
                    'full_name': pr.project
                },
                'ref': pr.branch,
            },
            'mergeable': True,
            'state': pr.state,
            'head': {
                'sha': pr.head_sha,
                'repo': {
                    'full_name': pr.project
                }
            },
            'merged': pr.is_merged,
            'body': pr.body
        }
        return data


class FakeIssueSearchResult(object):
    def __init__(self, issue):
        self.issue = issue


class FakeResponse(object):
    def __init__(self, data):
        self.status_code = 200
        self.data = data

    def json(self):
        return self.data


class FakeGithubSession(object):

    def __init__(self, data):
        self._data = data

    def build_url(self, *args):
        fakepath = '/'.join(args)
        return FAKE_BASE_URL + fakepath

    def get(self, url, headers=None):
        request = url
        if request.startswith(FAKE_BASE_URL):
            request = request[len(FAKE_BASE_URL):]

        entity, request = request.split('/', 1)

        if entity == 'repos':
            return self.get_repo(request)
        else:
            # unknown entity to process
            return None

    def get_repo(self, request):
        org, project, request = request.split('/', 2)
        project_name = '{}/{}'.format(org, project)

        client = FakeGithubClient(self._data)
        repo = client.repo_from_project(project_name)

        return repo.get_url(request)


class FakeGithubData(object):
    def __init__(self, pull_requests):
        self.pull_requests = pull_requests
        self.repos = {}
        self.required_contexts = {}


class FakeGithubClient(object):
    def __init__(self, data, inst_id=None):
        self._data = data
        self._inst_id = inst_id
        self.session = FakeGithubSession(data)

    def user(self, login):
        return FakeUser(login)

    def repository(self, owner, proj):
        return self._data.repos.get((owner, proj), None)

    def repo_from_project(self, project):
        # This is a convenience method for the tests.
        owner, proj = project.split('/')
        return self.repository(owner, proj)

    def addProject(self, project):
        owner, proj = project.name.split('/')
        self._data.repos[(owner, proj)] = FakeRepository(
            project.name, self._data)

    def addProjectByName(self, project_name):
        owner, proj = project_name.split('/')
        self._data.repos[(owner, proj)] = FakeRepository(
            project_name, self._data)

    def pull_request(self, owner, project, number):
        fake_pr = self._data.pull_requests[number]
        return FakePull(fake_pr)

    def search_issues(self, query):
        def tokenize(s):
            return re.findall(r'[\w]+', s)

        parts = tokenize(query)
        terms = set()
        results = []
        for part in parts:
            kv = part.split(':', 1)
            if len(kv) == 2:
                if kv[0] in set('type', 'is', 'in'):
                    # We only perform one search now and these aren't
                    # important; we can honor these terms later if
                    # necessary.
                    continue
            terms.add(part)

        for pr in self._data.pull_requests.values():
            if not pr.body:
                body = set()
            else:
                body = set(tokenize(pr.body))
            if terms.intersection(body):
                issue = FakeIssue(pr)
                results.append(FakeIssueSearchResult(issue))

        return results
