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
import json
import traceback

import cherrypy
import cachecontrol
from cachecontrol.cache import DictCache
from cachecontrol.heuristics import BaseHeuristic
import iso8601
import jwt
import requests
import voluptuous as v
import github3
import github3.exceptions

import gear

from zuul.connection import BaseConnection
from zuul.web.handler import BaseWebController
from zuul.lib.config import get_default
from zuul.model import Ref, Branch, Tag, Project
from zuul.exceptions import MergeFailure
from zuul.driver.github.githubmodel import PullRequest, GithubTriggerEvent

GITHUB_BASE_URL = 'https://api.github.com'
PREVIEW_JSON_ACCEPT = 'application/vnd.github.machine-man-preview+json'


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


class GithubGearmanWorker(object):
    """A thread that answers gearman requests"""
    log = logging.getLogger("zuul.GithubGearmanWorker")

    def __init__(self, connection):
        self.config = connection.sched.config
        self.connection = connection
        self.thread = threading.Thread(target=self._run,
                                       name='github-gearman-worker')
        self._running = False
        handler = "github:%s:payload" % self.connection.connection_name
        self.jobs = {
            handler: self.handle_payload,
        }

    def _run(self):
        while self._running:
            try:
                job = self.gearman.getJob()
                try:
                    if job.name not in self.jobs:
                        self.log.exception("Exception while running job")
                        job.sendWorkException(
                            traceback.format_exc().encode('utf8'))
                        continue
                    output = self.jobs[job.name](json.loads(job.arguments))
                    job.sendWorkComplete(json.dumps(output))
                except Exception:
                    self.log.exception("Exception while running job")
                    job.sendWorkException(
                        traceback.format_exc().encode('utf8'))
            except gear.InterruptedError:
                pass
            except Exception:
                self.log.exception("Exception while getting job")

    def handle_payload(self, args):
        headers = args.get("headers")
        body = args.get("body")

        delivery = headers.get('x-github-delivery')
        self.log.debug("Github Webhook Received: {delivery}".format(
            delivery=delivery))

        # TODO(jlk): Validate project in the request is a project we know

        try:
            self.__dispatch_event(body, headers)
            output = {'return_code': 200}
        except Exception:
            output = {'return_code': 503}
            self.log.exception("Exception handling Github event:")

        return output

    def __dispatch_event(self, body, headers):
        try:
            event = headers['x-github-event']
            self.log.debug("X-Github-Event: " + event)
        except KeyError:
            self.log.debug("Request headers missing the X-Github-Event.")
            raise Exception('Please specify a X-Github-Event header.')

        delivery = headers.get('x-github-delivery')
        try:
            self.connection.addEvent(body, event, delivery)
        except Exception:
            message = 'Exception deserializing JSON body'
            self.log.exception(message)
            # TODO(jlk): Raise this as something different?
            raise Exception(message)

    def start(self):
        self._running = True
        server = self.config.get('gearman', 'server')
        port = get_default(self.config, 'gearman', 'port', 4730)
        ssl_key = get_default(self.config, 'gearman', 'ssl_key')
        ssl_cert = get_default(self.config, 'gearman', 'ssl_cert')
        ssl_ca = get_default(self.config, 'gearman', 'ssl_ca')
        self.gearman = gear.TextWorker('Zuul Github Connector')
        self.log.debug("Connect to gearman")
        self.gearman.addServer(server, port, ssl_key, ssl_cert, ssl_ca)
        self.log.debug("Waiting for server")
        self.gearman.waitForServer()
        self.log.debug("Registering")
        for job in self.jobs:
            self.gearman.registerFunction(job)
        self.thread.start()

    def stop(self):
        self._running = False
        self.gearman.stopWaitingForJobs()
        # We join here to avoid whitelisting the thread -- if it takes more
        # than 5s to stop in tests, there's a problem.
        self.thread.join(timeout=5)
        self.gearman.shutdown()


class GithubEventConnector(threading.Thread):
    """Move events from GitHub into the scheduler"""

    log = logging.getLogger("zuul.GithubEventConnector")

    def __init__(self, connection):
        super(GithubEventConnector, self).__init__()
        self.daemon = True
        self.connection = connection
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.connection.addEvent(None)

    def _handleEvent(self):
        ts, json_body, event_type, delivery = self.connection.getEvent()
        if self._stopped:
            return

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
            event.delivery = delivery
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

        ref_parts = event.ref.split('/', 2)  # ie, ['refs', 'heads', 'foo/bar']

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

        if event.branch:
            if event.branch_deleted:
                # We currently cannot determine if a deleted branch was
                # protected so we need to assume it was. GitHub doesn't allow
                # deletion of protected branches but we don't get a
                # notification about branch protection settings. Thus we don't
                # know if branch protection has been disabled before deletion
                # of the branch.
                # FIXME(tobiash): Find a way to handle that case
                event.branch_protected = True
            elif event.branch_created:
                # A new branch never can be protected because that needs to be
                # configured after it has been created.
                event.branch_protected = False
            else:
                # An updated branch can be protected or not so we have to ask
                # GitHub whether it is.
                b = self.connection.getBranch(event.project_name, event.branch)
                event.branch_protected = b.get('protected')

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
        if not body.get('issue', {}).get('pull_request'):
            # Do not process non-PR issue comment
            return
        pr_body = self._issue_to_pull_request(body)
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
            # TODO(tobiash): it might be better to plumb in the installation id
            project = body.get('repository', {}).get('full_name')
            return self.connection.getUser(login, project)

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

    def __init__(self, username, connection, project):
        self._connection = connection
        self._username = username
        self._data = None
        self._project = project

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
            github = self._connection.getGithubClient(self._project)
            user = github.user(self._username)
            self.log.debug("Initialized data for user %s", self._username)
            log_rate_limit(self.log, github)
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

        if self.server == 'github.com':
            self.base_url = GITHUB_BASE_URL
        else:
            self.base_url = 'https://%s/api/v3' % self.server

        # ssl verification must default to true
        verify_ssl = self.connection_config.get('verify_ssl', 'true')
        self.verify_ssl = True
        if verify_ssl.lower() == 'false':
            self.verify_ssl = False

        self._github = None
        self.app_id = None
        self.app_key = None
        self.sched = None

        self.installation_map = {}
        self.installation_token_cache = {}

        # NOTE(jamielennox): Better here would be to cache to memcache or file
        # or something external - but zuul already sucks at restarting so in
        # memory probably doesn't make this much worse.

        # NOTE(tobiash): Unlike documented cachecontrol doesn't priorize
        # the etag caching but doesn't even re-request until max-age was
        # elapsed.
        #
        # Thus we need to add a custom caching heuristic which simply drops
        # the cache-control header containing max-age. This way we force
        # cachecontrol to only rely on the etag headers.
        #
        # http://cachecontrol.readthedocs.io/en/latest/etags.html
        # http://cachecontrol.readthedocs.io/en/latest/custom_heuristics.html
        class NoAgeHeuristic(BaseHeuristic):
            def update_headers(self, response):
                if 'cache-control' in response.headers:
                    del response.headers['cache-control']

        self.cache_adapter = cachecontrol.CacheControlAdapter(
            DictCache(),
            cache_etags=True,
            heuristic=NoAgeHeuristic())

        # The regex is based on the connection host. We do not yet support
        # cross-connection dependency gathering
        self.depends_on_re = re.compile(
            r"^Depends-On: https://%s/.+/.+/pull/[0-9]+$" % self.server,
            re.MULTILINE | re.IGNORECASE)

    def onLoad(self):
        self.log.info('Starting GitHub connection: %s' % self.connection_name)
        self.gearman_worker = GithubGearmanWorker(self)
        self.log.info('Authing to GitHub')
        self._authenticateGithubAPI()
        self._prime_installation_map()
        self.log.info('Starting event connector')
        self._start_event_connector()
        self.log.info('Starting GearmanWorker')
        self.gearman_worker.start()

    def onStop(self):
        # TODO(jeblair): remove this check which is here only so that
        # zuul-web can call connections.stop to shut down the sql
        # connection.
        if hasattr(self, 'gearman_worker'):
            self.gearman_worker.stop()
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

    def _get_installation_key(self, project, user_id=None, inst_id=None,
                              reprime=False):
        installation_id = inst_id
        if project is not None:
            installation_id = self.installation_map.get(project)

        if not installation_id:
            if reprime:
                # prime installation map and try again without refreshing
                self._prime_installation_map()
                return self._get_installation_key(project,
                                                  user_id=user_id,
                                                  inst_id=inst_id,
                                                  reprime=False)

            self.log.error("No installation ID available for project %s",
                           project)
            return ''

        now = datetime.datetime.now(utc)
        token, expiry = self.installation_token_cache.get(installation_id,
                                                          (None, None))

        if ((not expiry) or (not token) or (now >= expiry)):
            headers = self._get_app_auth_headers()

            url = "%s/installations/%s/access_tokens" % (self.base_url,
                                                         installation_id)

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

        url = '%s/app/installations' % self.base_url
        installations = []
        headers = self._get_app_auth_headers()
        page = 1
        while url:
            self.log.debug("Fetching installations for GitHub app "
                           "(page %s)" % page)
            page += 1
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            installations.extend(response.json())

            # check if we need to do further paged calls
            url = response.links.get(
                'next', {}).get('url')

        for install in installations:
            inst_id = install.get('id')
            token = self._get_installation_key(
                project=None, inst_id=inst_id)
            headers = {'Accept': PREVIEW_JSON_ACCEPT,
                       'Authorization': 'token %s' % token}

            url = '%s/installation/repositories?per_page=100' % self.base_url
            while url:
                self.log.debug("Fetching repos for install %s" % inst_id)
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                repos = response.json()

                for repo in repos.get('repositories'):
                    project_name = repo.get('full_name')
                    self.installation_map[project_name] = inst_id

                # check if we need to do further paged calls
                url = response.links.get('next', {}).get('url')

    def addEvent(self, data, event=None, delivery=None):
        return self.event_queue.put((time.time(), data, event, delivery))

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
        remove = set()
        for key, change in self._change_cache.items():
            if change not in relevant:
                remove.add(key)
        for key in remove:
            del self._change_cache[key]

    def getChange(self, event, refresh=False):
        """Get the change representing an event."""

        project = self.source.getProject(event.project_name)
        if event.change_number:
            change = self._getChange(project, event.change_number,
                                     event.patch_number, refresh=refresh)
            change.url = event.change_url
            change.uris = [
                '%s/%s/pull/%s' % (self.server, project, change.number),
            ]
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
            if hasattr(event, 'commits'):
                change.files = self.getPushedFileNames(event)
        return change

    def _getChange(self, project, number, patchset=None, refresh=False):
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
            self._updateChange(change)
        except Exception:
            if key in self._change_cache:
                del self._change_cache[key]
            raise
        return change

    def getChangesDependingOn(self, change, projects, tenant):
        changes = []
        if not change.uris:
            return changes

        # Get a list of projects with unique installation ids
        installation_ids = set()
        installation_projects = set()

        if projects:
            # We only need to find changes in projects in the supplied
            # ChangeQueue.  Find all of the github installations for
            # all of those projects, and search using each of them, so
            # that if we get the right results based on the
            # permissions granted to each of the installations.  The
            # common case for this is likely to be just one
            # installation -- change queues aren't likely to span more
            # than one installation.
            for project in projects:
                installation_id = self.installation_map.get(project.name)
                if installation_id not in installation_ids:
                    installation_ids.add(installation_id)
                    installation_projects.add(project.name)
        else:
            # We aren't in the context of a change queue and we just
            # need to query all installations of this tenant. This currently
            # only happens if certain features of the zuul trigger are
            # used; generally it should be avoided.
            for project_name, installation_id in self.installation_map.items():
                trusted, project = tenant.getProject(project_name)
                # ignore projects from different tenants
                if not project:
                    continue
                if installation_id not in installation_ids:
                    installation_ids.add(installation_id)
                    installation_projects.add(project_name)

        keys = set()
        pattern = ' OR '.join(change.uris)
        query = '%s type:pr is:open in:body' % pattern
        # Repeat the search for each installation id (project)
        for installation_project in installation_projects:
            github = self.getGithubClient(installation_project)
            for issue in github.search_issues(query=query):
                pr = issue.issue.pull_request().as_dict()
                if not pr.get('url'):
                    continue
                # the issue provides no good description of the project :\
                org, proj, _, num = pr.get('url').split('/')[-4:]
                proj = pr.get('base').get('repo').get('full_name')
                sha = pr.get('head').get('sha')
                key = (proj, num, sha)
                if key in keys:
                    continue
                self.log.debug("Found PR %s/%s needs %s/%s" %
                               (proj, num, change.project.name,
                                change.number))
                keys.add(key)
            self.log.debug("Ran search issues: %s", query)
            log_rate_limit(self.log, github)

        for key in keys:
            (proj, num, sha) = key
            project = self.source.getProject(proj)
            change = self._getChange(project, int(num), patchset=sha)
            changes.append(change)

        return changes

    def _updateChange(self, change):
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
        # ensure message is at least an empty string
        change.message = change.pr.get('body') or ''

        # Note(tobiash): The updated_at timestamp is a moving target that is
        # not bound to the pull request 'version' we can solve that by just not
        # updating the timestamp if the pull request is updated in the cache.
        # This way the old pull request object retains its old timestamp and
        # the update check works.
        if not change.updated_at:
            change.updated_at = self._ghTimestampToDate(
                change.pr.get('updated_at'))
        change.url = change.pr.get('url')
        change.uris = [
            '%s/%s/pull/%s' % (self.server, change.project.name,
                               change.number),
        ]

        if self.sched:
            self.sched.onChangeUpdated(change)

        return change

    def getGitUrl(self, project: Project):
        if self.git_ssh_key:
            return 'ssh://git@%s/%s.git' % (self.server, project.name)

        # if app_id is configured but self.app_id is empty we are not
        # authenticated yet against github as app
        if not self.app_id and self.connection_config.get('app_id', None):
            self._authenticateGithubAPI()
            self._prime_installation_map()

        if self.app_id:
            # We may be in the context of a merger or executor here. The
            # mergers and executors don't receive webhook events so they miss
            # new repository installations. In order to cope with this we need
            # to reprime the installation map if we don't find the repo there.
            installation_key = self._get_installation_key(project.name,
                                                          reprime=True)
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
        github = self.getGithubClient(project.name)
        exclude_unprotected = tenant.getExcludeUnprotectedBranches(project)

        url = github.session.build_url('repos', project.name,
                                       'branches')

        headers = {'Accept': 'application/vnd.github.loki-preview+json'}
        protected = 1 if exclude_unprotected else 0
        params = {'per_page': 100, 'protected': protected}

        branches = []
        while url:
            resp = github.session.get(
                url, headers=headers, params=params)

            # check if we need to do further paged calls
            url = resp.links.get(
                'next', {}).get('url')

            if resp.status_code == 403:
                self.log.error(str(resp))
                rate_limit = github.rate_limit()
                if rate_limit['resources']['core']['remaining'] == 0:
                    self.log.warning(
                        "Rate limit exceeded, using stale branch list")
                # failed to list branches so use a stale branch list
                return self._project_branch_cache.get(project.name, [])

            branches.extend([x['name'] for x in resp.json()])

        log_rate_limit(self.log, github)
        self._project_branch_cache[project.name] = branches
        return self._project_branch_cache[project.name]

    def getBranch(self, project_name, branch):
        github = self.getGithubClient(project_name)

        # Note that we directly use a web request here because if we use the
        # github3.py api directly we need a repository object which needs
        # an unneeded web request during creation.
        url = github.session.build_url('repos', project_name,
                                       'branches', branch)

        resp = github.session.get(url)

        if resp.status_code == 404:
            return None

        return resp.json()

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
        # NOTE: The mergeable call may get a false (null) while GitHub is
        # calculating if it can merge. The github3.py library will just return
        # that as false. This could lead to false negatives. So don't do this
        # call here and only evaluate branch protection settings. Any merge
        # conflicts which would block merging finally will be detected by
        # the zuul-mergers anyway.

        github = self.getGithubClient(change.project.name)
        owner, proj = change.project.name.split('/')
        pull = github.pull_request(owner, proj, change.number)

        protection = self._getBranchProtection(
            change.project.name, change.branch)

        if not self._hasRequiredStatusChecks(allow_needs, protection, pull):
            return False

        required_reviews = protection.get(
            'required_pull_request_reviews')
        if required_reviews:
            if required_reviews.get('require_code_owner_reviews'):
                # we need to process the reviews using code owners
                # TODO(tobiash): not implemented yet
                pass
            else:
                # we need to process the review using access rights
                # TODO(tobiash): not implemented yet
                pass

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

        permissions = {}
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

            if user in permissions:
                permission = permissions[user]
            else:
                permission = self.getRepoPermission(project.name, user)
                permissions[user] = permission

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

    def _getBranchProtection(self, project_name: str, branch: str):
        github = self.getGithubClient(project_name)
        url = github.session.build_url('repos', project_name,
                                       'branches', branch,
                                       'protection')

        headers = {'Accept': 'application/vnd.github.loki-preview+json'}
        resp = github.session.get(url, headers=headers)

        if resp.status_code == 404:
            return {}

        return resp.json()

    def _hasRequiredStatusChecks(self, allow_needs, protection, pull):
        if not protection:
            # There are no protection settings -> ok by definition
            return True

        required_contexts = protection.get(
            'required_status_checks', {}).get('contexts')

        if not required_contexts:
            # There are no required contexts -> ok by definition
            return True

        # Strip allow_needs as we will set this in the gate ourselves
        required_contexts = set(
            [x for x in required_contexts if x not in allow_needs])

        # NOTE(tobiash): We cannot just take the last commit in the list
        # because it is not sorted that the head is the last one in every case.
        # E.g. when doing a re-merge from the target the PR head can be
        # somewhere in the middle of the commit list. Thus we need to search
        # the whole commit list for the PR head commit which has the statuses
        # attached.
        commits = list(pull.commits())
        commit = None
        for c in commits:
            if c.sha == pull.head.sha:
                commit = c
                break

        # Get successful statuses
        successful = set(
            [s.context for s in commit.statuses() if s.state == 'success'])

        # Required contexts must be a subset of the successful contexts as
        # we allow additional successful status contexts we don't care about.
        return required_contexts.issubset(successful)

    def _getPullReviews(self, owner, project, number):
        # make a list out of the reviews so that we complete our
        # API transaction
        github = self.getGithubClient("%s/%s" % (owner, project))
        reviews = [review.as_dict() for review in
                   github.pull_request(owner, project, number).reviews()]

        self.log.debug('Got reviews for PR %s/%s#%s', owner, project, number)
        log_rate_limit(self.log, github)
        return reviews

    def getUser(self, login, project):
        return GithubUser(login, self, project)

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
        return perms.json().get('permission', 'none')

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

    def getWebController(self, zuul_web):
        return GithubWebController(zuul_web, self)

    def validateWebConfig(self, config, connections):
        if 'webhook_token' not in self.connection_config:
            raise Exception(
                "webhook_token not found in config for connection %s" %
                self.connection_name)
        return True


class GithubWebController(BaseWebController):

    log = logging.getLogger("zuul.GithubWebController")

    def __init__(self, zuul_web, connection):
        self.connection = connection
        self.zuul_web = zuul_web
        self.token = self.connection.connection_config.get('webhook_token')

    def _validate_signature(self, body, headers):
        try:
            request_signature = headers['x-hub-signature']
        except KeyError:
            raise cherrypy.HTTPError(401, 'X-Hub-Signature header missing.')

        payload_signature = _sign_request(body, self.token)

        self.log.debug("Payload Signature: {0}".format(str(payload_signature)))
        self.log.debug("Request Signature: {0}".format(str(request_signature)))
        if not hmac.compare_digest(
            str(payload_signature), str(request_signature)):
            raise cherrypy.HTTPError(
                401,
                'Request signature does not match calculated payload '
                'signature. Check that secret is correct.')

        return True

    @cherrypy.expose
    @cherrypy.tools.json_out(content_type='application/json; charset=utf-8')
    def payload(self):
        # Note(tobiash): We need to normalize the headers. Otherwise we will
        # have trouble to get them from the dict afterwards.
        # e.g.
        # GitHub: sent: X-GitHub-Event received: X-GitHub-Event
        # urllib: sent: X-GitHub-Event received: X-Github-Event
        #
        # We cannot easily solve this mismatch as every http processing lib
        # modifies the header casing in its own way and by specification http
        # headers are case insensitive so just lowercase all so we don't have
        # to take care later.
        # Note(corvus): Don't use cherrypy's json_in here so that we
        # can validate the signature.
        headers = dict()
        for key, value in cherrypy.request.headers.items():
            headers[key.lower()] = value
        body = cherrypy.request.body.read()
        self._validate_signature(body, headers)
        # We cannot send the raw body through gearman, so it's easy to just
        # encode it as json, after decoding it as utf-8
        json_body = json.loads(body.decode('utf-8'))

        job = self.zuul_web.rpc.submitJob(
            'github:%s:payload' % self.connection.connection_name,
            {'headers': headers, 'body': json_body})

        return json.loads(job.data[0])


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
