#!/usr/bin/env python

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

import os
import json
import urllib

import webob

from tests.base import ZuulTestCase, FIXTURE_DIR


class TestWebapp(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def setUp(self):
        super(TestWebapp, self).setUp()
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()
        self.port = self.webapp.server.socket.getsockname()[1]

    def tearDown(self):
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        super(TestWebapp, self).tearDown()

    def test_webapp_status(self):
        "Test that we can filter to only certain changes in the webapp."

        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/status" % self.port)
        f = urllib.request.urlopen(req)
        data = json.loads(f.read().decode('utf8'))

        self.assertIn('pipelines', data)

    def test_webapp_status_compat(self):
        # testing compat with status.json
        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/status.json" % self.port)
        f = urllib.request.urlopen(req)
        data = json.loads(f.read().decode('utf8'))

        self.assertIn('pipelines', data)

    def test_webapp_bad_url(self):
        # do we 404 correctly
        req = urllib.request.Request(
            "http://localhost:%s/status/foo" % self.port)
        self.assertRaises(urllib.error.HTTPError, urllib.request.urlopen, req)

    def test_webapp_find_change(self):
        # can we filter by change id
        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/status/change/1,1" % self.port)
        f = urllib.request.urlopen(req)
        data = json.loads(f.read().decode('utf8'))

        self.assertEqual(1, len(data), data)
        self.assertEqual("org/project", data[0]['project'])

        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/status/change/2,1" % self.port)
        f = urllib.request.urlopen(req)
        data = json.loads(f.read().decode('utf8'))

        self.assertEqual(1, len(data), data)
        self.assertEqual("org/project1", data[0]['project'], data)

    def test_webapp_keys(self):
        with open(os.path.join(FIXTURE_DIR, 'public.pem'), 'rb') as f:
            public_pem = f.read()

        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/keys/gerrit/org/project.pub" %
            self.port)
        f = urllib.request.urlopen(req)
        self.assertEqual(f.read(), public_pem)

    def test_webapp_custom_handler(self):
        def custom_handler(path, tenant_name, request):
            return webob.Response(body='ok')

        self.webapp.register_path('/custom', custom_handler)
        req = urllib.request.Request(
            "http://localhost:%s/custom" % self.port)
        f = urllib.request.urlopen(req)
        self.assertEqual(b'ok', f.read())

        self.webapp.unregister_path('/custom')
        self.assertRaises(urllib.error.HTTPError, urllib.request.urlopen, req)

    def test_webapp_404_on_unknown_tenant(self):
        req = urllib.request.Request(
            "http://localhost:{}/non-tenant/status.json".format(self.port))
        e = self.assertRaises(
            urllib.error.HTTPError, urllib.request.urlopen, req)
        self.assertEqual(404, e.code)
