# Copyright 2015 Hewlett-Packard Development Company, L.P.
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

import logging
import hmac
import hashlib
import time

import webob
import webob.dec
import voluptuous as v
import github3

from zuul.connection import BaseConnection
from zuul.model import PullRequest, Ref, TriggerEvent


class GithubWebhookListener():

    log = logging.getLogger("zuul.GithubWebhookListener")

    def __init__(self, connection):
        self.connection = connection

    def handle_request(self, path, tenant_name, request):
        if request.method != 'POST':
            self.log.debug("Only POST method is allowed.")
            raise webob.exc.HTTPMethodNotAllowed(
                'Only POST method is allowed.')

        self.log.debug("Github Webhook Received.")

        self._validate_signature(request)

        self.__dispatch_event(request)

    def __dispatch_event(self, request):
        try:
            event = request.headers['X-Github-Event']
            self.log.debug("X-Github-Event: " + event)
        except KeyError:
            self.log.debug("Request headers missing the X-Github-Event.")
            raise webob.exc.HTTPBadRequest('Please specify a X-Github-Event '
                                           'header.')

        try:
            method = getattr(self, '_event_' + event)
        except AttributeError:
            message = "Unhandled X-Github-Event: {0}".format(event)
            self.log.debug(message)
            raise webob.exc.HTTPBadRequest(message)

        try:
            event = method(request)
        except:
            self.log.exception('Exception when handling event:')

        if event:
            event.project_hostname = self.connection.canonical_hostname
            self.log.debug('Scheduling github event: {0}'.format(event.type))
            self.connection.sched.addEvent(event)

    def _event_pull_request(self, request):
        body = request.json_body
        action = body.get('action')
        pr_body = body.get('pull_request')

        event = self._pull_request_to_event(pr_body)

        event.type = 'pull_request'
        if action == 'opened':
            event.action = 'opened'
        elif action == 'synchronize':
            event.action = 'changed'
        elif action == 'closed':
            event.action = 'closed'
        elif action == 'reopened':
            event.action = 'reopened'
        else:
            return None

        return event

    def _validate_signature(self, request):
        secret = self.connection.connection_config.get('webhook_token', None)
        if secret is None:
            return True

        body = request.body
        try:
            request_signature = request.headers['X-Hub-Signature']
        except KeyError:
            raise webob.exc.HTTPUnauthorized(
                'Please specify a X-Hub-Signature header with secret.')

        payload_signature = 'sha1=' + hmac.new(secret,
                                               body,
                                               hashlib.sha1).hexdigest()

        self.log.debug("Payload Signature: {0}".format(str(payload_signature)))
        self.log.debug("Request Signature: {0}".format(str(request_signature)))
        if str(payload_signature) != str(request_signature):
            raise webob.exc.HTTPUnauthorized(
                'Request signature does not match calculated payload '
                'signature. Check that secret is correct.')

        return True

    def _pull_request_to_event(self, pr_body):
        event = TriggerEvent()
        event.trigger_name = 'github'

        base = pr_body.get('base')
        base_repo = base.get('repo')
        head = pr_body.get('head')

        event.project_name = base_repo.get('full_name')
        event.change_number = pr_body.get('number')
        event.change_url = self.connection.getPullUrl(event.project_name,
                                                      event.change_number)
        event.updated_at = pr_body.get('updated_at')
        event.branch = base.get('ref')
        event.refspec = "refs/pull/" + str(pr_body.get('number')) + "/head"
        event.patch_number = head.get('sha')

        return event


class GithubConnection(BaseConnection):
    driver_name = 'github'
    log = logging.getLogger("connection.github")
    payload_path = 'payload'

    def __init__(self, driver, connection_name, connection_config):
        super(GithubConnection, self).__init__(
            driver, connection_name, connection_config)
        self.github = None
        self.canonical_hostname = self.connection_config.get(
            'canonical_hostname', 'github.com')
        self._change_cache = {}
        self.projects = {}
        self.source = driver.getSource(self)

    def onLoad(self):
        webhook_listener = GithubWebhookListener(self)
        self.registerHttpHandler(self.payload_path,
                                 webhook_listener.handle_request)
        self._authenticateGithubAPI()

    def onStop(self):
        self.unregisterHttpHandler(self.payload_path)

    def _authenticateGithubAPI(self):
        token = self.connection_config.get('api_token', None)
        if token is not None:
            self.github = github3.login(token)
            self.log.info("Github API Authentication successful.")
        else:
            self.github = None
            self.log.info(
                "No Github credentials found in zuul configuration, cannot "
                "authenticate.")

    def maintainCache(self, relevant):
        for key, change in self._change_cache.items():
            if change not in relevant:
                del self._change_cache[key]

    def getChange(self, event):
        """Get the change representing an event."""

        if event.change_number:
            change = PullRequest(event.project_name)
            change.project = self.source.getProject(event.project_name)
            change.number = event.change_number
            change.refspec = event.refspec
            change.branch = event.branch
            change.url = event.change_url
            change.updated_at = self._ghTimestampToDate(event.updated_at)
            change.patchset = event.patch_number
        else:
            project = self.source.getProject(event.project_name)
            change = Ref(project)
        return change

    def getGitUrl(self, project):
        url = 'https://%s/%s' % ("github.com", project)
        return url

    def getGitwebUrl(self, project, sha=None):
        url = 'https://%s/%s' % ("github.com", project)
        if sha is not None:
            url += '/commit/%s' % sha
        return url

    def getProject(self, name):
        return self.projects.get(name)

    def addProject(self, project):
        self.projects[project.name] = project

    def getProjectBranches(self, project):
        owner, proj = project.name.split('/')
        repository = self.github.repository(owner, proj)
        branches = [branch.name for branch in repository.branches()]
        return branches

    def getPullUrl(self, project, number):
        return '%s/pull/%s' % (self.getGitwebUrl(project), number)

    def _ghTimestampToDate(self, timestamp):
        return time.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')


def getSchema():
    github_connection = v.Any(str, v.Schema({}, extra=True))
    return github_connection
