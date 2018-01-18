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
        self._state = state
        self._url = url
        self._description = description
        self._context = context
        self._user = user

    def as_dict(self):
        return {
            'state': self._state,
            'url': self._url,
            'description': self._description,
            'context': self._context,
            'creator': {
                'login': self._user
            }
        }


class FakeCommit(object):
    def __init__(self):
        self._statuses = []

    def set_status(self, state, url, description, context, user):
        status = FakeStatus(
            state, url, description, context, user)
        # always insert a status to the front of the list, to represent
        # the last status provided for a commit.
        self._statuses.insert(0, status)

    def statuses(self):
        return self._statuses


class FakeRepository(object):
    def __init__(self):
        self._branches = [FakeBranch()]
        self._commits = {}

    def branches(self, protected=False):
        if protected:
            # simulate there is no protected branch
            return []
        return self._branches

    def create_status(self, sha, state, url, description, context,
                      user='zuul'):
        # Since we're bypassing github API, which would require a user, we
        # default the user as 'zuul' here.
        commit = self._commits.get(sha, None)
        if commit is None:
            commit = FakeCommit()
            self._commits[sha] = commit
        commit.set_status(state, url, description, context, user)

    def commit(self, sha):
        commit = self._commits.get(sha, None)
        if commit is None:
            commit = FakeCommit()
            self._commits[sha] = commit
        return commit


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


class FakeGithub(object):
    def __init__(self, pull_requests):
        self._pull_requests = pull_requests
        self._repos = {}

    def user(self, login):
        return FakeUser(login)

    def repository(self, owner, proj):
        return self._repos.get((owner, proj), None)

    def repo_from_project(self, project):
        # This is a convenience method for the tests.
        owner, proj = project.split('/')
        return self.repository(owner, proj)

    def addProject(self, project):
        owner, proj = project.name.split('/')
        self._repos[(owner, proj)] = FakeRepository()

    def pull_request(self, owner, project, number):
        fake_pr = self._pull_requests[number]
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

        for pr in self._pull_requests.values():
            if not pr.body:
                body = set()
            else:
                body = set(tokenize(pr.body))
            if terms.intersection(body):
                issue = FakeIssue(pr)
                results.append(FakeIssueSearchResult(issue))

        return results
