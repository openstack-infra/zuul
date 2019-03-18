# Copyright 2014 Hewlett-Packard Development Company, L.P.
# Copyright 2014 Rackspace Australia
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

import json
import os
import urllib.parse
import socket

import requests

import zuul.web

from tests.base import ZuulTestCase, ZuulDBTestCase, AnsibleZuulTestCase
from tests.base import ZuulWebFixture, FIXTURE_DIR


class FakeConfig(object):

    def __init__(self, config):
        self.config = config or {}

    def has_option(self, section, option):
        return option in self.config.get(section, {})

    def get(self, section, option):
        return self.config.get(section, {}).get(option)


class BaseTestWeb(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'
    config_ini_data = {}

    def setUp(self):
        super(BaseTestWeb, self).setUp()

        self.zuul_ini_config = FakeConfig(self.config_ini_data)

        # Start the web server
        self.web = self.useFixture(
            ZuulWebFixture(
                self.gearman_server.port,
                self.config,
                info=zuul.model.WebInfo.fromConfig(self.zuul_ini_config),
                zk_hosts=self.zk_config))

        self.executor_server.hold_jobs_in_build = True

        self.host = 'localhost'
        self.port = self.web.port
        # Wait until web server is started
        while True:
            try:
                with socket.create_connection((self.host, self.port)):
                    break
            except ConnectionRefusedError:
                pass
        self.base_url = "http://{host}:{port}".format(
            host=self.host, port=self.port)

    def add_base_changes(self):
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

    def get_url(self, url, *args, **kwargs):
        return requests.get(
            urllib.parse.urljoin(self.base_url, url), *args, **kwargs)

    def tearDown(self):
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        super(BaseTestWeb, self).tearDown()


class TestWeb(BaseTestWeb):

    def test_web_status(self):
        "Test that we can retrieve JSON status info"
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('project-merge')
        self.waitUntilSettled()

        resp = self.get_url("api/tenant/tenant-one/status")
        self.assertIn('Content-Length', resp.headers)
        self.assertIn('Content-Type', resp.headers)
        self.assertEqual(
            'application/json; charset=utf-8', resp.headers['Content-Type'])
        self.assertIn('Access-Control-Allow-Origin', resp.headers)
        self.assertIn('Cache-Control', resp.headers)
        self.assertIn('Last-Modified', resp.headers)
        self.assertTrue(resp.headers['Last-Modified'].endswith(' GMT'))

        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        data = resp.json()
        status_jobs = []
        for p in data['pipelines']:
            for q in p['change_queues']:
                if p['name'] in ['gate', 'conflict']:
                    self.assertEqual(q['window'], 20)
                else:
                    self.assertEqual(q['window'], 0)
                for head in q['heads']:
                    for change in head:
                        self.assertIn(
                            'review.example.com/org/project',
                            change['project_canonical'])
                        self.assertTrue(change['active'])
                        self.assertIn(change['id'], ('1,1', '2,1', '3,1'))
                        for job in change['jobs']:
                            status_jobs.append(job)
        self.assertEqual('project-merge', status_jobs[0]['name'])
        # TODO(mordred) pull uuids from self.builds
        self.assertEqual(
            'stream/{uuid}?logfile=console.log'.format(
                uuid=status_jobs[0]['uuid']),
            status_jobs[0]['url'])
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[0]['uuid']),
            status_jobs[0]['finger_url'])
        # TOOD(mordred) configure a success-url on the base job
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[0]['uuid']),
            status_jobs[0]['report_url'])
        self.assertEqual('project-test1', status_jobs[1]['name'])
        self.assertEqual(
            'stream/{uuid}?logfile=console.log'.format(
                uuid=status_jobs[1]['uuid']),
            status_jobs[1]['url'])
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[1]['uuid']),
            status_jobs[1]['finger_url'])
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[1]['uuid']),
            status_jobs[1]['report_url'])

        self.assertEqual('project-test2', status_jobs[2]['name'])
        self.assertEqual(
            'stream/{uuid}?logfile=console.log'.format(
                uuid=status_jobs[2]['uuid']),
            status_jobs[2]['url'])
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[2]['uuid']),
            status_jobs[2]['finger_url'])
        self.assertEqual(
            'finger://{hostname}/{uuid}'.format(
                hostname=self.executor_server.hostname,
                uuid=status_jobs[2]['uuid']),
            status_jobs[2]['report_url'])

        # check job dependencies
        self.assertIsNotNone(status_jobs[0]['dependencies'])
        self.assertIsNotNone(status_jobs[1]['dependencies'])
        self.assertIsNotNone(status_jobs[2]['dependencies'])
        self.assertEqual(len(status_jobs[0]['dependencies']), 0)
        self.assertEqual(len(status_jobs[1]['dependencies']), 1)
        self.assertEqual(len(status_jobs[2]['dependencies']), 1)
        self.assertIn('project-merge', status_jobs[1]['dependencies'])
        self.assertIn('project-merge', status_jobs[2]['dependencies'])

    def test_web_tenants(self):
        "Test that we can retrieve JSON status info"
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        self.waitUntilSettled()

        self.executor_server.release('project-merge')
        self.waitUntilSettled()

        resp = self.get_url("api/tenants")
        self.assertIn('Content-Length', resp.headers)
        self.assertIn('Content-Type', resp.headers)
        self.assertEqual(
            'application/json; charset=utf-8', resp.headers['Content-Type'])
        # self.assertIn('Access-Control-Allow-Origin', resp.headers)
        # self.assertIn('Cache-Control', resp.headers)
        # self.assertIn('Last-Modified', resp.headers)
        data = resp.json()

        self.assertEqual('tenant-one', data[0]['name'])
        self.assertEqual(3, data[0]['projects'])
        self.assertEqual(3, data[0]['queue'])

        # release jobs and check if the queue size is 0
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        data = self.get_url("api/tenants").json()
        self.assertEqual('tenant-one', data[0]['name'])
        self.assertEqual(3, data[0]['projects'])
        self.assertEqual(0, data[0]['queue'])

        # test that non-live items are not counted
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        B.setDependsOn(A, 1)
        self.fake_gerrit.addEvent(B.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

        req = urllib.request.Request(
            "http://127.0.0.1:%s/api/tenants" % self.port)
        f = urllib.request.urlopen(req)
        data = f.read().decode('utf8')
        data = json.loads(data)

        self.assertEqual('tenant-one', data[0]['name'])
        self.assertEqual(3, data[0]['projects'])
        self.assertEqual(1, data[0]['queue'])

    def test_web_bad_url(self):
        # do we redirect to index.html
        resp = self.get_url("status/foo")
        self.assertEqual(200, resp.status_code)

    def test_web_find_change(self):
        # can we filter by change id
        self.add_base_changes()
        data = self.get_url("api/tenant/tenant-one/status/change/1,1").json()

        self.assertEqual(1, len(data), data)
        self.assertEqual("org/project", data[0]['project'])

        data = self.get_url("api/tenant/tenant-one/status/change/2,1").json()

        self.assertEqual(1, len(data), data)
        self.assertEqual("org/project1", data[0]['project'], data)

    def test_web_find_job(self):
        # can we fetch the variants for a single job
        data = self.get_url('api/tenant/tenant-one/job/project-test1').json()

        common_config_role = {
            'implicit': True,
            'project_canonical_name': 'review.example.com/common-config',
            'target_name': 'common-config',
            'type': 'zuul',
        }
        source_ctx = {
            'branch': 'master',
            'path': 'zuul.yaml',
            'project': 'common-config',
        }
        run = [{
            'path': 'playbooks/project-test1.yaml',
            'roles': [{
                'implicit': True,
                'project_canonical_name': 'review.example.com/common-config',
                'target_name': 'common-config',
                'type': 'zuul'
            }],
            'secrets': [],
            'source_context': source_ctx,
        }]

        self.assertEqual([
            {
                'name': 'project-test1',
                'abstract': False,
                'ansible_version': None,
                'attempts': 4,
                'branches': [],
                'dependencies': [],
                'description': None,
                'files': [],
                'irrelevant_files': [],
                'final': False,
                'implied_branch': None,
                'nodeset': {
                    'groups': [],
                    'name': '',
                    'nodes': [{'comment': None,
                               'hold_job': None,
                               'label': 'label1',
                               'name': 'controller',
                               'aliases': [],
                               'state': 'unknown'}],
                },
                'parent': 'base',
                'post_review': None,
                'protected': None,
                'provides': [],
                'required_projects': [],
                'requires': [],
                'roles': [common_config_role],
                'run': run,
                'pre_run': [],
                'post_run': [],
                'semaphore': None,
                'source_context': source_ctx,
                'tags': [],
                'timeout': None,
                'variables': {},
                'variant_description': '',
                'voting': True
            }, {
                'name': 'project-test1',
                'abstract': False,
                'ansible_version': None,
                'attempts': 3,
                'branches': ['stable'],
                'dependencies': [],
                'description': None,
                'files': [],
                'irrelevant_files': [],
                'final': False,
                'implied_branch': None,
                'nodeset': {
                    'groups': [],
                    'name': '',
                    'nodes': [{'comment': None,
                               'hold_job': None,
                               'label': 'label2',
                               'name': 'controller',
                               'aliases': [],
                               'state': 'unknown'}],
                },
                'parent': 'base',
                'post_review': None,
                'protected': None,
                'provides': [],
                'required_projects': [],
                'requires': [],
                'roles': [common_config_role],
                'run': run,
                'pre_run': [],
                'post_run': [],
                'semaphore': None,
                'source_context': source_ctx,
                'tags': [],
                'timeout': None,
                'variables': {},
                'variant_description': 'stable',
                'voting': True
            }], data)

        data = self.get_url('api/tenant/tenant-one/job/test-job').json()
        run[0]['path'] = 'playbooks/project-merge.yaml'
        self.assertEqual([
            {
                'abstract': False,
                'ansible_version': None,
                'attempts': 3,
                'branches': [],
                'dependencies': [],
                'description': None,
                'files': [],
                'final': False,
                'implied_branch': None,
                'irrelevant_files': [],
                'name': 'test-job',
                'parent': 'base',
                'post_review': None,
                'protected': None,
                'provides': [],
                'required_projects': [
                    {'override_branch': None,
                     'override_checkout': None,
                     'project_name': 'review.example.com/org/project'}],
                'requires': [],
                'roles': [common_config_role],
                'run': run,
                'pre_run': [],
                'post_run': [],
                'semaphore': None,
                'source_context': source_ctx,
                'tags': [],
                'timeout': None,
                'variables': {},
                'variant_description': '',
                'voting': True
            }], data)

    def test_find_job_complete_playbooks(self):
        # can we fetch the variants for a single job
        data = self.get_url('api/tenant/tenant-one/job/complete-job').json()

        def expected_pb(path):
            return {
                'path': path,
                'roles': [{
                    'implicit': True,
                    'project_canonical_name':
                    'review.example.com/common-config',
                    'target_name': 'common-config',
                    'type': 'zuul'
                }],
                'secrets': [],
                'source_context': {
                    'branch': 'master',
                    'path': 'zuul.yaml',
                    'project': 'common-config',
                }
            }
        self.assertEqual([
            expected_pb("playbooks/run.yaml")
        ], data[0]['run'])
        self.assertEqual([
            expected_pb("playbooks/pre-run.yaml")
        ], data[0]['pre_run'])
        self.assertEqual([
            expected_pb("playbooks/post-run-01.yaml"),
            expected_pb("playbooks/post-run-02.yaml")
        ], data[0]['post_run'])

    def test_web_nodes_list(self):
        # can we fetch the nodes list
        self.add_base_changes()
        data = self.get_url('api/tenant/tenant-one/nodes').json()
        self.assertGreater(len(data), 0)
        self.assertEqual("test-provider", data[0]["provider"])
        self.assertEqual("label1", data[0]["type"])

    def test_web_labels_list(self):
        # can we fetch the labels list
        data = self.get_url('api/tenant/tenant-one/labels').json()
        expected_list = [{'name': 'label1'}]
        self.assertEqual(expected_list, data)

    def test_web_pipeline_list(self):
        # can we fetch the list of pipelines
        data = self.get_url('api/tenant/tenant-one/pipelines').json()

        expected_list = [
            {'name': 'check'},
            {'name': 'gate'},
            {'name': 'post'},
        ]
        self.assertEqual(expected_list, data)

    def test_web_project_list(self):
        # can we fetch the list of projects
        data = self.get_url('api/tenant/tenant-one/projects').json()

        expected_list = [
            {'name': 'common-config', 'type': 'config'},
            {'name': 'org/project', 'type': 'untrusted'},
            {'name': 'org/project1', 'type': 'untrusted'},
            {'name': 'org/project2', 'type': 'untrusted'}
        ]
        for p in expected_list:
            p["canonical_name"] = "review.example.com/%s" % p["name"]
            p["connection_name"] = "gerrit"
        self.assertEqual(expected_list, data)

    def test_web_project_get(self):
        # can we fetch project details
        data = self.get_url(
            'api/tenant/tenant-one/project/org/project1').json()

        jobs = [[{'abstract': False,
                  'ansible_version': None,
                  'attempts': 3,
                  'branches': [],
                  'dependencies': [],
                  'description': None,
                  'files': [],
                  'final': False,
                  'implied_branch': None,
                  'irrelevant_files': [],
                  'name': 'project-merge',
                  'parent': 'base',
                  'post_review': None,
                  'protected': None,
                  'provides': [],
                  'required_projects': [],
                  'requires': [],
                  'roles': [],
                  'run': [],
                  'pre_run': [],
                  'post_run': [],
                  'semaphore': None,
                  'source_context': {
                      'branch': 'master',
                      'path': 'zuul.yaml',
                      'project': 'common-config'},
                  'tags': [],
                  'timeout': None,
                  'variables': {},
                  'variant_description': '',
                  'voting': True}],
                [{'abstract': False,
                  'ansible_version': None,
                  'attempts': 3,
                  'branches': [],
                  'dependencies': [{'name': 'project-merge',
                                    'soft': False}],
                  'description': None,
                  'files': [],
                  'final': False,
                  'implied_branch': None,
                  'irrelevant_files': [],
                  'name': 'project-test1',
                  'parent': 'base',
                  'post_review': None,
                  'protected': None,
                  'provides': [],
                  'required_projects': [],
                  'requires': [],
                  'roles': [],
                  'run': [],
                  'pre_run': [],
                  'post_run': [],
                  'semaphore': None,
                  'source_context': {
                      'branch': 'master',
                      'path': 'zuul.yaml',
                      'project': 'common-config'},
                  'tags': [],
                  'timeout': None,
                  'variables': {},
                  'variant_description': '',
                  'voting': True}],
                [{'abstract': False,
                  'ansible_version': None,
                  'attempts': 3,
                  'branches': [],
                  'dependencies': [{'name': 'project-merge',
                                    'soft': False}],
                  'description': None,
                  'files': [],
                  'final': False,
                  'implied_branch': None,
                  'irrelevant_files': [],
                  'name': 'project-test2',
                  'parent': 'base',
                  'post_review': None,
                  'protected': None,
                  'provides': [],
                  'required_projects': [],
                  'requires': [],
                  'roles': [],
                  'run': [],
                  'pre_run': [],
                  'post_run': [],
                  'semaphore': None,
                  'source_context': {
                      'branch': 'master',
                      'path': 'zuul.yaml',
                      'project': 'common-config'},
                  'tags': [],
                  'timeout': None,
                  'variables': {},
                  'variant_description': '',
                  'voting': True}],
                [{'abstract': False,
                  'ansible_version': None,
                  'attempts': 3,
                  'branches': [],
                  'dependencies': [{'name': 'project-merge',
                                    'soft': False}],
                  'description': None,
                  'files': [],
                  'final': False,
                  'implied_branch': None,
                  'irrelevant_files': [],
                  'name': 'project1-project2-integration',
                  'parent': 'base',
                  'post_review': None,
                  'protected': None,
                  'provides': [],
                  'required_projects': [],
                  'requires': [],
                  'roles': [],
                  'run': [],
                  'pre_run': [],
                  'post_run': [],
                  'semaphore': None,
                  'source_context': {
                      'branch': 'master',
                      'path': 'zuul.yaml',
                      'project': 'common-config'},
                  'tags': [],
                  'timeout': None,
                  'variables': {},
                  'variant_description': '',
                  'voting': True}]]

        self.assertEqual(
            {
                'canonical_name': 'review.example.com/org/project1',
                'connection_name': 'gerrit',
                'name': 'org/project1',
                'configs': [{
                    'templates': [],
                    'default_branch': 'master',
                    'merge_mode': 'merge-resolve',
                    'pipelines': [{
                        'name': 'check',
                        'queue_name': None,
                        'jobs': jobs,
                    }, {
                        'name': 'gate',
                        'queue_name': 'integrated',
                        'jobs': jobs,
                    }]
                }]
            }, data)

    def test_web_keys(self):
        with open(os.path.join(FIXTURE_DIR, 'public.pem'), 'rb') as f:
            public_pem = f.read()

        resp = self.get_url("api/tenant/tenant-one/key/org/project.pub")
        self.assertEqual(resp.content, public_pem)
        self.assertIn('text/plain', resp.headers.get('Content-Type'))

        resp = self.get_url("api/tenant/non-tenant/key/org/project.pub")
        self.assertEqual(404, resp.status_code)

        resp = self.get_url("api/tenant/tenant-one/key/org/no-project.pub")
        self.assertEqual(404, resp.status_code)

        with open(os.path.join(FIXTURE_DIR, 'ssh.pub'), 'rb') as f:
            public_ssh = f.read()

        resp = self.get_url("api/tenant/tenant-one/project-ssh-key/"
                            "org/project.pub")
        self.assertEqual(resp.content, public_ssh)
        self.assertIn('text/plain', resp.headers.get('Content-Type'))

    def test_web_404_on_unknown_tenant(self):
        resp = self.get_url("api/tenant/non-tenant/status")
        self.assertEqual(404, resp.status_code)

    def test_jobs_list(self):
        jobs = self.get_url("api/tenant/tenant-one/jobs").json()
        self.assertEqual(len(jobs), 10)

        resp = self.get_url("api/tenant/non-tenant/jobs")
        self.assertEqual(404, resp.status_code)

    def test_jobs_list_variants(self):
        resp = self.get_url("api/tenant/tenant-one/jobs").json()
        for job in resp:
            if job['name'] in ["base", "noop"]:
                variants = None
            elif job['name'] == 'project-test1':
                variants = [
                    {'parent': 'base'},
                    {'branches': ['stable'], 'parent': 'base'},
                ]
            else:
                variants = [{'parent': 'base'}]
            self.assertEqual(variants, job.get('variants'))

    def test_web_job_noop(self):
        job = self.get_url("api/tenant/tenant-one/job/noop").json()
        self.assertEqual("noop", job[0]["name"])


class TestWebSecrets(BaseTestWeb):
    tenant_config_file = 'config/secrets/main.yaml'

    def test_web_find_job_secret(self):
        data = self.get_url('api/tenant/tenant-one/job/project1-secret').json()
        run = data[0]['run']
        secret = {'name': 'project1_secret', 'alias': 'secret_name'}
        self.assertEqual([secret], run[0]['secrets'])


class TestInfo(BaseTestWeb):

    def setUp(self):
        super(TestInfo, self).setUp()
        web_config = self.config_ini_data.get('web', {})
        self.websocket_url = web_config.get('websocket_url')
        self.stats_url = web_config.get('stats_url')
        statsd_config = self.config_ini_data.get('statsd', {})
        self.stats_prefix = statsd_config.get('prefix')

    def test_info(self):
        info = self.get_url("api/info").json()
        self.assertEqual(
            info, {
                "info": {
                    "capabilities": {
                        "job_history": False
                    },
                    "stats": {
                        "url": self.stats_url,
                        "prefix": self.stats_prefix,
                        "type": "graphite",
                    },
                    "websocket_url": self.websocket_url,
                }
            })

    def test_tenant_info(self):
        info = self.get_url("api/tenant/tenant-one/info").json()
        self.assertEqual(
            info, {
                "info": {
                    "tenant": "tenant-one",
                    "capabilities": {
                        "job_history": False
                    },
                    "stats": {
                        "url": self.stats_url,
                        "prefix": self.stats_prefix,
                        "type": "graphite",
                    },
                    "websocket_url": self.websocket_url,
                }
            })


class TestTenantInfoConfigBroken(BaseTestWeb):

    tenant_config_file = 'config/broken/main.yaml'

    def test_tenant_info_broken_config(self):
        config_errors = self.get_url(
            "api/tenant/tenant-one/config-errors").json()
        self.assertEqual(
            len(config_errors), 1)
        self.assertEqual(
            config_errors[0]['source_context']['project'], 'org/project2')
        self.assertEqual(
            config_errors[0]['source_context']['branch'], 'master')
        self.assertEqual(
            config_errors[0]['source_context']['path'], '.zuul.yaml')
        self.assertIn('Zuul encountered a syntax error',
                      config_errors[0]['error'])

        resp = self.get_url("api/tenant/non-tenant/config-errors")
        self.assertEqual(404, resp.status_code)


class TestWebSocketInfo(TestInfo):

    config_ini_data = {
        'web': {
            'websocket_url': 'wss://ws.example.com'
        }
    }


class TestGraphiteUrl(TestInfo):

    config_ini_data = {
        'statsd': {
            'prefix': 'example'
        },
        'web': {
            'stats_url': 'https://graphite.example.com',
        }
    }


class TestBuildInfo(ZuulDBTestCase, BaseTestWeb):
    config_file = 'zuul-sql-driver.conf'
    tenant_config_file = 'config/sql-driver/main.yaml'

    def test_web_list_builds(self):
        # Generate some build records in the db.
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        builds = self.get_url("api/tenant/tenant-one/builds").json()
        self.assertEqual(len(builds), 6)

        uuid = builds[0]['uuid']
        build = self.get_url("api/tenant/tenant-one/build/%s" % uuid).json()
        self.assertEqual(build['job_name'], builds[0]['job_name'])

        resp = self.get_url("api/tenant/tenant-one/build/1234")
        self.assertEqual(404, resp.status_code)

        builds_query = self.get_url("api/tenant/tenant-one/builds?"
                                    "project=org/project&"
                                    "project=org/project1").json()
        self.assertEqual(len(builds_query), 6)

        resp = self.get_url("api/tenant/non-tenant/builds")
        self.assertEqual(404, resp.status_code)

    def test_web_list_buildsets(self):
        # Generate some build records in the db.
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        buildsets = self.get_url("api/tenant/tenant-one/buildsets").json()
        self.assertEqual(2, len(buildsets))
        project_bs = [x for x in buildsets if x["project"] == "org/project"][0]

        buildset = self.get_url(
            "api/tenant/tenant-one/buildset/%s" % project_bs['uuid']).json()
        self.assertEqual(3, len(buildset["builds"]))

        project_test1_build = [x for x in buildset["builds"]
                               if x["job_name"] == "project-test1"][0]
        self.assertEqual('SUCCESS', project_test1_build['result'])

        project_test2_build = [x for x in buildset["builds"]
                               if x["job_name"] == "project-test2"][0]
        self.assertEqual('SUCCESS', project_test2_build['result'])

        project_merge_build = [x for x in buildset["builds"]
                               if x["job_name"] == "project-merge"][0]
        self.assertEqual('SUCCESS', project_merge_build['result'])


class TestArtifacts(ZuulDBTestCase, BaseTestWeb, AnsibleZuulTestCase):
    config_file = 'zuul-sql-driver.conf'
    tenant_config_file = 'config/sql-driver/main.yaml'

    def test_artifacts(self):
        # Generate some build records in the db.
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        build_query = self.get_url("api/tenant/tenant-one/builds?"
                                   "project=org/project&"
                                   "job_name=project-test1").json()
        self.assertEqual(len(build_query), 1)
        self.assertEqual(len(build_query[0]['artifacts']), 3)
        arts = build_query[0]['artifacts']
        arts.sort(key=lambda x: x['name'])
        self.assertEqual(build_query[0]['artifacts'], [
            {'url': 'http://example.com/docs',
             'name': 'docs'},
            {'url': 'http://logs.example.com/build/relative/docs',
             'name': 'relative',
             'metadata': {'foo': 'bar'}},
            {'url': 'http://example.com/tarball',
             'name': 'tarball'},
        ])

    def test_buildset_artifacts(self):
        self.add_base_changes()
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()

        buildsets = self.get_url("api/tenant/tenant-one/buildsets").json()
        project_bs = [x for x in buildsets if x["project"] == "org/project"][0]
        buildset = self.get_url(
            "api/tenant/tenant-one/buildset/%s" % project_bs['uuid']).json()
        self.assertEqual(3, len(buildset["builds"]))

        test1_build = [x for x in buildset["builds"]
                       if x["job_name"] == "project-test1"][0]
        arts = test1_build['artifacts']
        arts.sort(key=lambda x: x['name'])
        self.assertEqual([
            {'url': 'http://example.com/docs',
             'name': 'docs'},
            {'url': 'http://logs.example.com/build/relative/docs',
             'name': 'relative',
             'metadata': {'foo': 'bar'}},
            {'url': 'http://example.com/tarball',
             'name': 'tarball'},
        ], test1_build['artifacts'])
