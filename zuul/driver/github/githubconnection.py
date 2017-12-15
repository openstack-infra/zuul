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

import collections
import datetime
import logging
import hmac
import hashlib
import queue
import threading
import time
import re

import cachecontrol
from cachecontrol.cache import DictCache
import iso8601
import jwt
import requests
import webob
import webob.dec
import voluptuous as v
import github3
import github3.exceptions

from zuul.connection import BaseConnection
from zuul.model import Ref, Branch, Tag, Project
from zuul.exceptions import MergeFailure
from zuul.driver.github.githubmodel import PullRequest, GithubTriggerEvent

ACCESS_TOKEN_URL = 'https://api.github.com/installations/%s/access_tokens'
PREVIEW_JSON_ACCEPT = 'application/vnd.github.machine-man-preview+json'
INSTALLATIONS_URL = 'https://api.github.com/app/installations'
REPOS_URL = 'https://api.github.com/installation/repositories'


def _sign_request(body, secret):
    signature = 'sha1=' + hmac.new(
        secret.encode('utf-8'), body, hashlib.sha1).hexdigest()
    return signature


class UTC(datetime.tzinfo):
    """UTC"""

    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return datetime.timedelta(0)


utc = UTC()


class GithubWebhookListener():

    log = logging.getLogger("zuul.GithubWebhookListener")

    def __init__(self, connection):
        self.connection = connection

    def handle_request(self, path, tenant_name, request):
        if request.method != 'POST':
            self.log.debug("Only POST method is allowed.")
            raise webob.exc.HTTPMethodNotAllowed(
                'Only POST method is allowed.')

        delivery = request.headers.get('X-GitHub-Delivery')
        self.log.debug("Github Webhook Received: {delivery}".format(
            delivery=delivery))

        self._validate_signature(request)
        # TODO(jlk): Validate project in the request is a project we know

        try:
            self.__dispatch_event(request)
        except Exception:
            self.log.exception("Exception handling Github event:")

    def __dispatch_event(self, request):
        try:
            event = request.headers['X-Github-Event']
            self.log.debug("X-Github-Event: " + event)
        except KeyError:
            self.log.debug("Request headers missing the X-Github-Event.")
            raise webob.exc.HTTPBadRequest('Please specify a X-Github-Event '
                                           'header.')

        try:
            json_body = request.json_body
            self.connection.addEvent(json_body, event)
        except Exception:
            message = 'Exception deserializing JSON body'
            self.log.exception(message)
            raise webob.exc.HTTPBadRequest(message)

    def _validate_signature(self, request):
        secret = self.connection.connection_config.get('webhook_token', None)
        if secret is None:
            raise RuntimeError("webhook_token is required")

        body = request.body
        try:
            request_signature = request.headers['X-Hub-Signature']
        except KeyError:
            raise webob.exc.HTTPUnauthorized(
                'Please specify a X-Hub-Signature header with secret.')

        payload_signature = _sign_request(body, secret)

        self.log.debug("Payload Signature: {0}".format(str(payload_signature)))
        self.log.debug("Request Signature: {0}".format(str(request_signature)))
        if not hmac.compare_digest(
            str(payload_signature), str(request_signature)):
            raise webob.exc.HTTPUnauthorized(
                'Request signature does not match calculated payload '
                'signature. Check that secret is correct.')

        return True


class GithubEventConnector(threading.Thread):
    """Move events from GitHub into the scheduler"""

    log = logging.getLogger("zuul.GithubEventConnector")
    delay = 10.0

    def __init__(self, connection):
        super(GithubEventConnector, self).__init__()
        self.daemon = True
        self.connection = connection
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.connection.addEvent(None)

    def _handleEvent(self):
        ts, json_body, event_type = self.connection.getEvent()
        if self._stopped:
            return
        # Github can produce inconsistent data immediately after an
        # event, So ensure that we do not deliver the event to Zuul
        # until at least a certain amount of time has passed.  Note
        # that if we receive several events in succession, we will
        # only need to delay for the first event.  In essence, Zuul
        # should always be a constant number of seconds behind Github.
        now = time.time()
        time.sleep(max((ts + self.delay) - now, 0.0))

        # If there's any installation mapping information in the body then
        # update the project mapping before any requests are made.
        installation_id = json_body.get('installation', {}).get('id')
        project_name = json_body.get('repository', {}).get('full_name')

        if installation_id and project_name:
            old_id = self.connection.installation_map.get(project_name)

            if old_id and old_id != installation_id:
                msg = "Unexpected installation_id change for %s. %d -> %d."
                self.log.warning(msg, project_name, old_id, installation_id)

            self.connection.installation_map[project_name] = installation_id

        try:
            method = getattr(self, '_event_' + event_type)
        except AttributeError:
            # TODO(jlk): Gracefully handle event types we don't care about
            # instead of logging an exception.
            message = "Unhandled X-Github-Event: {0}".format(event_type)
            self.log.debug(message)
            # Returns empty on unhandled events
            return

        try:
            event = method(json_body)
        except Exception:
            self.log.exception('Exception when handling event:')
            event = None

        if event:
            if event.change_number:
                project = self.connection.source.getProject(event.project_name)
                self.connection._getChange(project,
                                           event.change_number,
                                           event.patch_number,
                                           refresh=True)
            event.project_hostname = self.connection.canonical_hostname
            self.connection.logEvent(event)
            self.connection.sched.addEvent(event)

    def _event_push(self, body):
        base_repo = body.get('repository')

        event = GithubTriggerEvent()
        event.trigger_name = 'github'
        event.project_name = base_repo.get('full_name')
        event.type = 'push'
        event.branch_updated = True

        event.ref = body.get('ref')
        event.oldrev = body.get('before')
        event.newrev = body.get('after')
        event.commits = body.get('commits')

        ref_parts = event.ref.split('/')  # ie, ['refs', 'heads', 'master']

        if ref_parts[1] == "heads":
            # necessary for the scheduler to match against particular branches
            event.branch = ref_parts[2]

        # This checks whether the event created or deleted a branch so
        # that Zuul may know to perform a reconfiguration on the
        # project.
        if event.oldrev == '0' * 40:
            event.branch_created = True
        if event.newrev == '0' * 40:
            event.branch_deleted = True

        return event

    def _event_pull_request(self, body):
        action = body.get('action')
        pr_body = body.get('pull_request')

        event = self._pull_request_to_event(pr_body)
        event.account = self._get_sender(body)

        event.type = 'pull_request'
        if action == 'opened':
            event.action = 'opened'
        elif action == 'synchronize':
            event.action = 'changed'
        elif action == 'closed':
            event.action = 'closed'
        elif action == 'reopened':
            event.action = 'reopened'
        elif action == 'labeled':
            event.action = 'labeled'
            event.label = body['label']['name']
        elif action == 'unlabeled':
            event.action = 'unlabeled'
            event.label = body['label']['name']
        elif action == 'edited':
            event.action = 'edited'
        else:
            return None

        return event

    def _event_issue_comment(self, body):
        """Handles pull request comments"""
        action = body.get('action')
        if action != 'created':
            return
        pr_body = self._issue_to_pull_request(body)
        number = body.get('issue').get('number')
        project_name = body.get('repository').get('full_name')
        pr_body = self.connection.getPull(project_name, number)
        if pr_body is None:
            return

        event = self._pull_request_to_event(pr_body)
        event.account = self._get_sender(body)
        event.comment = body.get('comment').get('body')
        event.type = 'pull_request'
        event.action = 'comment'
        return event

    def _event_pull_request_review(self, body):
        """Handles pull request reviews"""
        pr_body = body.get('pull_request')
        if pr_body is None:
            return

        review = body.get('review')
        if review is None:
            return

        event = self._pull_request_to_event(pr_body)
        event.state = review.get('state')
        event.account = self._get_sender(body)
        event.type = 'pull_request_review'
        event.action = body.get('action')
        return event

    def _event_status(self, body):
        action = body.get('action')
        if action == 'pending':
            return
        project = body.get('name')
        pr_body = self.connection.getPullBySha(body['sha'], project)
        if pr_body is None:
            return

        event = self._pull_request_to_event(pr_body)
        event.account = self._get_sender(body)
        event.type = 'pull_request'
        event.action = 'status'
        # Github API is silly. Webhook blob sets author data in
        # 'sender', but API call to get status puts it in 'creator'.
        # Duplicate the data so our code can look in one place
        body['creator'] = body['sender']
        event.status = "%s:%s:%s" % _status_as_tuple(body)
        return event

    def _issue_to_pull_request(self, body):
        number = body.get('issue').get('number')
        project_name = body.get('repository').get('full_name')
        pr_body = self.connection.getPull(project_name, number)
        if pr_body is None:
            self.log.debug('Pull request #%s not found in project %s' %
                           (number, project_name))
        return pr_body

    def _pull_request_to_event(self, pr_body):
        event = GithubTriggerEvent()
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
        event.ref = "refs/pull/" + str(pr_body.get('number')) + "/head"
        event.patch_number = head.get('sha')

        event.title = pr_body.get('title')

        return event

    def _get_sender(self, body):
        login = body.get('sender').get('login')
        if login:
            return self.connection.getUser(login)

    def run(self):
        while True:
            if self._stopped:
                return
            try:
                self._handleEvent()
            except Exception:
                self.log.exception("Exception moving GitHub event:")
            finally:
                self.connection.eventDone()


class GithubUser(collections.Mapping):
    log = logging.getLogger('zuul.GithubUser')

    def __init__(self, github, username):
        self._github = github
        self._username = username
        self._data = None

    def __getitem__(self, key):
        self._init_data()
        return self._data[key]

    def __iter__(self):
        self._init_data()
        return iter(self._data)

    def __len__(self):
        self._init_data()
        return len(self._data)

    def _init_data(self):
        if self._data is None:
            user = self._github.user(self._username)
            self.log.debug("Initialized data for user %s", self._username)
            log_rate_limit(self.log, self._github)
            self._data = {
                'username': user.login,
                'name': user.name,
                'email': user.email
            }


class GithubConnection(BaseConnection):
    driver_name = 'github'
    log = logging.getLogger("zuul.GithubConnection")
    payload_path = 'payload'

    def __init__(self, driver, connection_name, connection_config):
        super(GithubConnection, self).__init__(
            driver, connection_name, connection_config)
        self._change_cache = {}
        self._project_branch_cache = {}
        self.projects = {}
        self.git_ssh_key = self.connection_config.get('sshkey')
        self.server = self.connection_config.get('server', 'github.com')
        self.canonical_hostname = self.connection_config.get(
            'canonical_hostname', self.server)
        self.source = driver.getSource(self)
        self.event_queue = queue.Queue()

        # ssl verification must default to true
        verify_ssl = self.connection_config.get('verify_ssl', 'true')
        self.verify_ssl = True
        if verify_ssl.lower() == 'false':
            self.verify_ssl = False

        self._github = None
        self.app_id = None
        self.app_key = None

        self.installation_map = {}
        self.installation_token_cache = {}

        # NOTE(jamielennox): Better here would be to cache to memcache or file
        # or something external - but zuul already sucks at restarting so in
        # memory probably doesn't make this much worse.
        self.cache_adapter = cachecontrol.CacheControlAdapter(
            DictCache(),
            cache_etags=True)

        # The regex is based on the connection host. We do not yet support
        # cross-connection dependency gathering
        self.depends_on_re = re.compile(
            r"^Depends-On: https://%s/.+/.+/pull/[0-9]+$" % self.server,
            re.MULTILINE | re.IGNORECASE)

    def onLoad(self):
        webhook_listener = GithubWebhookListener(self)
        self.registerHttpHandler(self.payload_path,
                                 webhook_listener.handle_request)
        self._authenticateGithubAPI()
        self._prime_installation_map()
        self._start_event_connector()

    def onStop(self):
        self.unregisterHttpHandler(self.payload_path)
        self._stop_event_connector()

    def _start_event_connector(self):
        self.github_event_connector = GithubEventConnector(self)
        self.github_event_connector.start()

    def _stop_event_connector(self):
        if self.github_event_connector:
            self.github_event_connector.stop()
            self.github_event_connector.join()

    def _createGithubClient(self):
        if self.server != 'github.com':
            url = 'https://%s/' % self.server
            if not self.verify_ssl:
                # disabling ssl verification is evil so emit a warning
                self.log.warning("SSL verification disabled for "
                                 "GitHub Enterprise")
            github = github3.GitHubEnterprise(url, verify=self.verify_ssl)
        else:
            github = github3.GitHub()

        # anything going through requests to http/s goes through cache
        github.session.mount('http://', self.cache_adapter)
        github.session.mount('https://', self.cache_adapter)
        # Add properties to store project and user for logging later
        github._zuul_project = None
        github._zuul_user_id = None
        return github

    def _authenticateGithubAPI(self):
        config = self.connection_config

        api_token = config.get('api_token')

        app_id = config.get('app_id')
        app_key = None
        app_key_file = config.get('app_key')

        self._github = self._createGithubClient()

        if api_token:
            self._github.login(token=api_token)

        if app_key_file:
            try:
                with open(app_key_file, 'r') as f:
                    app_key = f.read()
            except IOError:
                m = "Failed to open app key file for reading: %s"
                self.log.error(m, app_key_file)

        if (app_id or app_key) and \
                not (app_id and app_key):
            self.log.warning("You must provide an app_id and "
                             "app_key to use installation based "
                             "authentication")

            return

        if app_id:
            self.app_id = int(app_id)
        if app_key:
            self.app_key = app_key

    def _get_app_auth_headers(self):
        now = datetime.datetime.now(utc)
        expiry = now + datetime.timedelta(minutes=5)

        data = {'iat': now, 'exp': expiry, 'iss': self.app_id}
        app_token = jwt.encode(data,
                               self.app_key,
                               algorithm='RS256').decode('utf-8')

        headers = {'Accept': PREVIEW_JSON_ACCEPT,
                   'Authorization': 'Bearer %s' % app_token}

        return headers

    def _get_installation_key(self, project, user_id=None, inst_id=None):
        installation_id = inst_id
        if project is not None:
            installation_id = self.installation_map.get(project)

        if not installation_id:
            self.log.error("No installation ID available for project %s",
                           project)
            return ''

        now = datetime.datetime.now(utc)
        token, expiry = self.installation_token_cache.get(installation_id,
                                                          (None, None))

        if ((not expiry) or (not token) or (now >= expiry)):
            headers = self._get_app_auth_headers()
            url = ACCESS_TOKEN_URL % installation_id
            json_data = {'user_id': user_id} if user_id else None

            response = requests.post(url, headers=headers, json=json_data)
            response.raise_for_status()

            data = response.json()

            expiry = iso8601.parse_date(data['expires_at'])
            expiry -= datetime.timedelta(minutes=2)
            token = data['token']

            self.installation_token_cache[installation_id] = (token, expiry)

        return token

    def _prime_installation_map(self):
        """Walks each app install for the repos to prime install IDs"""

        if not self.app_id:
            return

        url = INSTALLATIONS_URL
        headers = self._get_app_auth_headers()
        self.log.debug("Fetching installations for GitHub app")
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()

        for install in data:
            inst_id = install.get('id')
            token = self._get_installation_key(project=None, inst_id=inst_id)
            headers = {'Accept': PREVIEW_JSON_ACCEPT,
                       'Authorization': 'token %s' % token}
            url = REPOS_URL
            self.log.debug("Fetching repos for install %s" % inst_id)
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            repos = response.json()

            for repo in repos.get('repositories'):
                project_name = repo.get('full_name')
                self.installation_map[project_name] = inst_id

    def addEvent(self, data, event=None):
        return self.event_queue.put((time.time(), data, event))

    def getEvent(self):
        return self.event_queue.get()

    def eventDone(self):
        self.event_queue.task_done()

    def getGithubClient(self,
                        project=None,
                        user_id=None):
        # if you're authenticating for a project and you're an integration then
        # you need to use the installation specific token.
        if project and self.app_id:
            github = self._createGithubClient()
            github.login(token=self._get_installation_key(project, user_id))
            github._zuul_project = project
            github._zuul_user_id = user_id
            return github

        # if we're using api_key authentication then this is already token
        # authenticated, if not then anonymous is the best we have.
        return self._github

    def maintainCache(self, relevant):
        for key, change in self._change_cache.items():
            if change not in relevant:
                del self._change_cache[key]

    def getChange(self, event, refresh=False):
        """Get the change representing an event."""

        project = self.source.getProject(event.project_name)
        if event.change_number:
            change = self._getChange(project, event.change_number,
                                     event.patch_number, refresh=refresh)
            change.url = event.change_url
            change.updated_at = self._ghTimestampToDate(event.updated_at)
            change.source_event = event
            change.is_current_patchset = (change.pr.get('head').get('sha') ==
                                          event.patch_number)
        else:
            if event.ref and event.ref.startswith('refs/tags/'):
                change = Tag(project)
                change.tag = event.ref[len('refs/tags/'):]
            elif event.ref and event.ref.startswith('refs/heads/'):
                change = Branch(project)
                change.branch = event.ref[len('refs/heads/'):]
            else:
                change = Ref(project)
            change.ref = event.ref
            change.oldrev = event.oldrev
            change.newrev = event.newrev
            change.url = self.getGitwebUrl(project, sha=event.newrev)
            change.source_event = event
            change.files = self.getPushedFileNames(event)
        return change

    def _getChange(self, project, number, patchset=None, refresh=False,
                   history=None):
        key = (project.name, number, patchset)
        change = self._change_cache.get(key)
        if change and not refresh:
            return change
        if not change:
            change = PullRequest(project.name)
            change.project = project
            change.number = number
            change.patchset = patchset
        self._change_cache[key] = change
        try:
            self._updateChange(change, history)
        except Exception:
            if key in self._change_cache:
                del self._change_cache[key]
            raise
        return change

    def _getDependsOnFromPR(self, body):
        prs = []
        seen = set()

        for match in self.depends_on_re.findall(body):
            if match in seen:
                self.log.debug("Ignoring duplicate Depends-On: %s" % (match,))
                continue
            seen.add(match)
            # Get the github url
            url = match.rsplit()[-1]
            # break it into the parts we need
            _, org, proj, _, num = url.rsplit('/', 4)
            # Get a pull object so we can get the head sha
            pull = self.getPull('%s/%s' % (org, proj), int(num))
            prs.append(pull)

        return prs

    def _getNeededByFromPR(self, change):
        prs = []
        seen = set()
        # This shouldn't return duplicate issues, but code as if it could

        # This leaves off the protocol, but looks for the specific GitHub
        # hostname, the org/project, and the pull request number.
        pattern = 'Depends-On %s/%s/pull/%s' % (self.server,
                                                change.project.name,
                                                change.number)
        query = '%s type:pr is:open in:body' % pattern
        github = self.getGithubClient()
        for issue in github.search_issues(query=query):
            pr = issue.issue.pull_request().as_dict()
            if not pr.get('url'):
                continue
            if issue in seen:
                continue
            # the issue provides no good description of the project :\
            org, proj, _, num = pr.get('url').split('/')[-4:]
            self.log.debug("Found PR %s/%s/%s needs %s/%s" %
                           (org, proj, num, change.project.name,
                            change.number))
            prs.append(pr)
            seen.add(issue)

        self.log.debug("Ran search issues: %s", query)
        log_rate_limit(self.log, github)
        return prs

    def _updateChange(self, change, history=None):

        # If this change is already in the history, we have a cyclic
        # dependency loop and we do not need to update again, since it
        # was done in a previous frame.
        if history and (change.project.name, change.number) in history:
            return change

        self.log.info("Updating %s" % (change,))
        change.pr = self.getPull(change.project.name, change.number)
        change.ref = "refs/pull/%s/head" % change.number
        change.branch = change.pr.get('base').get('ref')
        change.files = change.pr.get('files')
        change.title = change.pr.get('title')
        change.open = change.pr.get('state') == 'open'
        change.is_merged = change.pr.get('merged')
        change.status = self._get_statuses(change.project,
                                           change.patchset)
        change.reviews = self.getPullReviews(change.project,
                                             change.number)
        change.labels = change.pr.get('labels')
        change.body = change.pr.get('body')
        # ensure body is at least an empty string
        if not change.body:
            change.body = ''

        if history is None:
            history = []
        else:
            history = history[:]
        history.append((change.project.name, change.number))

        needs_changes = []

        # Get all the PRs this may depend on
        for pr in self._getDependsOnFromPR(change.body):
            proj = pr.get('base').get('repo').get('full_name')
            pull = pr.get('number')
            self.log.debug("Updating %s: Getting dependent "
                           "pull request %s/%s" %
                           (change, proj, pull))
            project = self.source.getProject(proj)
            dep = self._getChange(project, pull,
                                  patchset=pr.get('head').get('sha'),
                                  history=history)
            if (not dep.is_merged) and dep not in needs_changes:
                needs_changes.append(dep)

        change.needs_changes = needs_changes

        needed_by_changes = []
        for pr in self._getNeededByFromPR(change):
            proj = pr.get('base').get('repo').get('full_name')
            pull = pr.get('number')
            self.log.debug("Updating %s: Getting needed "
                           "pull request %s/%s" %
                           (change, proj, pull))
            project = self.source.getProject(proj)
            dep = self._getChange(project, pull,
                                  patchset=pr.get('head').get('sha'),
                                  history=history)
            if not dep.is_merged:
                needed_by_changes.append(dep)
        change.needed_by_changes = needed_by_changes

        return change

    def getGitUrl(self, project: Project):
        if self.git_ssh_key:
            return 'ssh://git@%s/%s.git' % (self.server, project.name)

        if self.app_id:
            installation_key = self._get_installation_key(project.name)
            return 'https://x-access-token:%s@%s/%s' % (installation_key,
                                                        self.server,
                                                        project.name)

        return 'https://%s/%s' % (self.server, project.name)

    def getGitwebUrl(self, project, sha=None):
        url = 'https://%s/%s' % (self.server, project)
        if sha is not None:
            url += '/commit/%s' % sha
        return url

    def getProject(self, name):
        return self.projects.get(name)

    def addProject(self, project):
        self.projects[project.name] = project

    def getProjectBranches(self, project, tenant):

        # Evaluate if unprotected branches should be excluded or not. The first
        # match wins. The order is project -> tenant (default is false).
        project_config = tenant.project_configs.get(project.canonical_name)
        if project_config.exclude_unprotected_branches is not None:
            exclude_unprotected = project_config.exclude_unprotected_branches
        else:
            exclude_unprotected = tenant.exclude_unprotected_branches

        github = self.getGithubClient(project.name)
        try:
            owner, proj = project.name.split('/')
            repository = github.repository(owner, proj)
            self._project_branch_cache[project.name] = [
                branch.name for branch in repository.branches(
                    protected=exclude_unprotected)]
            self.log.debug('Got project branches for %s', project.name)
            log_rate_limit(self.log, github)
        except github3.exceptions.ForbiddenError as e:
            self.log.error(str(e), exc_info=True)
            rate_limit = github.rate_limit()
            if rate_limit['resources']['core']['remaining'] == 0:
                self.log.debug("Rate limit exceeded, using stale branch list")
            else:
                self.log.error(str(e), exc_info=True)

        return self._project_branch_cache[project.name]

    def getPullUrl(self, project, number):
        return '%s/pull/%s' % (self.getGitwebUrl(project), number)

    def getPull(self, project_name, number):
        github = self.getGithubClient(project_name)
        owner, proj = project_name.split('/')
        for retry in range(5):
            probj = github.pull_request(owner, proj, number)
            if probj is not None:
                break
            self.log.warning("Pull request #%s of %s/%s returned None!" % (
                             number, owner, proj))
            time.sleep(1)
        # Get the issue obj so we can get the labels (this is silly)
        issueobj = probj.issue()
        pr = probj.as_dict()
        pr['files'] = [f.filename for f in probj.files()]
        pr['labels'] = [l.name for l in issueobj.labels()]
        self.log.debug('Got PR %s#%s', project_name, number)
        log_rate_limit(self.log, github)
        return pr

    def canMerge(self, change, allow_needs):
        # This API call may get a false (null) while GitHub is calculating
        # if it can merge.  The github3.py library will just return that as
        # false. This could lead to false negatives.
        # Additionally, this only checks if the PR code could merge
        # cleanly to the target branch. It does not evaluate any branch
        # protection merge requirements (such as reviews and status states)
        # At some point in the future this may be available through the API
        # or we can fetch the branch protection settings and evaluate within
        # Zuul whether or not those protections have been met
        # For now, just send back a True value.
        return True

    def getPullBySha(self, sha, project):
        pulls = []
        owner, project = project.split('/')
        github = self.getGithubClient("%s/%s" % (owner, project))
        repo = github.repository(owner, project)
        for pr in repo.pull_requests(state='open'):
            if pr.head.sha != sha:
                continue
            if pr.as_dict() in pulls:
                continue
            pulls.append(pr.as_dict())

        self.log.debug('Got PR on project %s for sha %s', project, sha)
        log_rate_limit(self.log, github)
        if len(pulls) > 1:
            raise Exception('Multiple pulls found with head sha %s' % sha)

        if len(pulls) == 0:
            return None
        return pulls.pop()

    def getPullReviews(self, project, number):
        owner, proj = project.name.split('/')

        revs = self._getPullReviews(owner, proj, number)

        reviews = {}
        for rev in revs:
            user = rev.get('user').get('login')
            review = {
                'by': {
                    'username': user,
                    'email': rev.get('user').get('email'),
                },
                'grantedOn': int(time.mktime(self._ghTimestampToDate(
                                             rev.get('submitted_at')))),
            }

            review['type'] = rev.get('state').lower()
            review['submitted_at'] = rev.get('submitted_at')

            # Get user's rights. A user always has read to leave a review
            review['permission'] = 'read'
            permission = self.getRepoPermission(project.name, user)
            if permission == 'write':
                review['permission'] = 'write'
            if permission == 'admin':
                review['permission'] = 'admin'

            if user not in reviews:
                reviews[user] = review
            else:
                # if there are multiple reviews per user, keep the newest
                # note that this breaks the ability to set the 'older-than'
                # option on a review requirement.
                # BUT do not keep the latest if it's a 'commented' type and the
                # previous review was 'approved' or 'changes_requested', as
                # the GitHub model does not change the vote if a comment is
                # added after the fact. THANKS GITHUB!
                if review['grantedOn'] > reviews[user]['grantedOn']:
                    if (review['type'] == 'commented' and reviews[user]['type']
                            in ('approved', 'changes_requested')):
                        self.log.debug("Discarding comment review %s due to "
                                       "an existing vote %s" % (review,
                                                                reviews[user]))
                        pass
                    else:
                        reviews[user] = review

        return reviews.values()

    def _getPullReviews(self, owner, project, number):
        # make a list out of the reviews so that we complete our
        # API transaction
        github = self.getGithubClient("%s/%s" % (owner, project))
        reviews = [review.as_dict() for review in
                   github.pull_request(owner, project, number).reviews()]

        self.log.debug('Got reviews for PR %s/%s#%s', owner, project, number)
        log_rate_limit(self.log, github)
        return reviews

    def getUser(self, login):
        return GithubUser(self.getGithubClient(), login)

    def getUserUri(self, login):
        return 'https://%s/%s' % (self.server, login)

    def getRepoPermission(self, project, login):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        # This gets around a missing API call
        # need preview header
        headers = {'Accept': 'application/vnd.github.korra-preview'}

        # Create a repo object
        repository = github.repository(owner, proj)

        if not repository:
            return 'none'

        # Build up a URL
        url = repository._build_url('collaborators', login, 'permission',
                                    base_url=repository._api)
        # Get the data
        perms = repository._get(url, headers=headers)

        self.log.debug("Got repo permissions for %s/%s", owner, proj)
        log_rate_limit(self.log, github)

        # no known user, maybe deleted since review?
        if perms.status_code == 404:
            return 'none'

        # get permissions from the data
        return perms.json()['permission']

    def commentPull(self, project, pr_number, message):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        repository = github.repository(owner, proj)
        pull_request = repository.issue(pr_number)
        pull_request.create_comment(message)
        self.log.debug("Commented on PR %s/%s#%s", owner, proj, pr_number)
        log_rate_limit(self.log, github)

    def mergePull(self, project, pr_number, commit_message='', sha=None):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        pull_request = github.pull_request(owner, proj, pr_number)
        try:
            result = pull_request.merge(commit_message=commit_message, sha=sha)
        except github3.exceptions.MethodNotAllowed as e:
            raise MergeFailure('Merge was not successful due to mergeability'
                               ' conflict, original error is %s' % e)

        self.log.debug("Merged PR %s/%s#%s", owner, proj, pr_number)
        log_rate_limit(self.log, github)
        if not result:
            raise Exception('Pull request was not merged')

    def getCommitStatuses(self, project, sha):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        repository = github.repository(owner, proj)
        commit = repository.commit(sha)
        # make a list out of the statuses so that we complete our
        # API transaction
        statuses = [status.as_dict() for status in commit.statuses()]

        self.log.debug("Got commit statuses for sha %s on %s", sha, project)
        log_rate_limit(self.log, github)
        return statuses

    def setCommitStatus(self, project, sha, state, url='', description='',
                        context=''):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        repository = github.repository(owner, proj)
        repository.create_status(sha, state, url, description, context)
        self.log.debug("Set commit status to %s for sha %s on %s",
                       state, sha, project)
        log_rate_limit(self.log, github)

    def labelPull(self, project, pr_number, label):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        pull_request = github.issue(owner, proj, pr_number)
        pull_request.add_labels(label)
        self.log.debug("Added label %s to %s#%s", label, proj, pr_number)
        log_rate_limit(self.log, github)

    def unlabelPull(self, project, pr_number, label):
        github = self.getGithubClient(project)
        owner, proj = project.split('/')
        pull_request = github.issue(owner, proj, pr_number)
        pull_request.remove_label(label)
        self.log.debug("Removed label %s from %s#%s", label, proj, pr_number)
        log_rate_limit(self.log, github)

    def getPushedFileNames(self, event):
        files = set()
        for c in event.commits:
            for f in c.get('added') + c.get('modified') + c.get('removed'):
                files.add(f)
        return list(files)

    def _ghTimestampToDate(self, timestamp):
        return time.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')

    def _get_statuses(self, project, sha):
        # A ref can have more than one status from each context,
        # however the API returns them in order, newest first.
        # So we can keep track of which contexts we've already seen
        # and throw out the rest. Our unique key is based on
        # the user and the context, since context is free form and anybody
        # can put whatever they want there. We want to ensure we track it
        # by user, so that we can require/trigger by user too.
        seen = []
        statuses = []
        for status in self.getCommitStatuses(project.name, sha):
            stuple = _status_as_tuple(status)
            if "%s:%s" % (stuple[0], stuple[1]) not in seen:
                statuses.append("%s:%s:%s" % stuple)
                seen.append("%s:%s" % (stuple[0], stuple[1]))

        return statuses


def _status_as_tuple(status):
    """Translate a status into a tuple of user, context, state"""

    creator = status.get('creator')
    if not creator:
        user = "Unknown"
    else:
        user = creator.get('login')
    context = status.get('context')
    state = status.get('state')
    return (user, context, state)


def log_rate_limit(log, github):
    try:
        rate_limit = github.rate_limit()
        remaining = rate_limit['resources']['core']['remaining']
        reset = rate_limit['resources']['core']['reset']
    except Exception:
        return
    if github._zuul_user_id:
        log.debug('GitHub API rate limit (%s, %s) remaining: %s reset: %s',
                  github._zuul_project, github._zuul_user_id, remaining, reset)
    else:
        log.debug('GitHub API rate limit remaining: %s reset: %s',
                  remaining, reset)


def getSchema():
    github_connection = v.Any(str, v.Schema(dict))
    return github_connection
