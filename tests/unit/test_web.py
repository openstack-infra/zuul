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

import asyncio
import threading
import os
import json
import urllib
import time
import socket
from unittest import skip

import webob

import zuul.web

from tests.base import ZuulTestCase, FIXTURE_DIR


class TestWeb(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def setUp(self):
        super(TestWeb, self).setUp()
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(A.addApproval('Approved', 1))
        B = self.fake_gerrit.addFakeChange('org/project1', 'master', 'B')
        B.addApproval('Code-Review', 2)
        self.fake_gerrit.addEvent(B.addApproval('Approved', 1))
        self.waitUntilSettled()

        # Start the web server
        self.web = zuul.web.ZuulWeb(
            listen_address='127.0.0.1', listen_port=0,
            gear_server='127.0.0.1', gear_port=self.gearman_server.port)
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        ws_thread = threading.Thread(target=self.web.run, args=(loop,))
        ws_thread.start()
        self.addCleanup(loop.close)
        self.addCleanup(ws_thread.join)
        self.addCleanup(self.web.stop)

        self.host = 'localhost'
        # Wait until web server is started
        while True:
            time.sleep(0.1)
            if self.web.server is None:
                continue
            self.port = self.web.server.sockets[0].getsockname()[1]
            print(self.host, self.port)
            try:
                with socket.create_connection((self.host, self.port)):
                    break
            except ConnectionRefusedError:
                pass

    def tearDown(self):
        self.executor_server.hold_jobs_in_build = False
        self.executor_server.release()
        self.waitUntilSettled()
        super(TestWeb, self).tearDown()

    def test_web_status(self):
        "Test that we can filter to only certain changes in the webapp."

        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/status.json" % self.port)
        f = urllib.request.urlopen(req)
        data = json.loads(f.read().decode('utf8'))

        self.assertIn('pipelines', data)

    def test_web_bad_url(self):
        # do we 404 correctly
        req = urllib.request.Request(
            "http://localhost:%s/status/foo" % self.port)
        self.assertRaises(urllib.error.HTTPError, urllib.request.urlopen, req)

    @skip("This is not supported by zuul-web")
    def test_web_find_change(self):
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

    def test_web_keys(self):
        with open(os.path.join(FIXTURE_DIR, 'public.pem'), 'rb') as f:
            public_pem = f.read()

        req = urllib.request.Request(
            "http://localhost:%s/tenant-one/org/project.pub" %
            self.port)
        f = urllib.request.urlopen(req)
        self.assertEqual(f.read(), public_pem)

    @skip("This may not apply to zuul-web")
    def test_web_custom_handler(self):
        def custom_handler(path, tenant_name, request):
            return webob.Response(body='ok')

        self.webapp.register_path('/custom', custom_handler)
        req = urllib.request.Request(
            "http://localhost:%s/custom" % self.port)
        f = urllib.request.urlopen(req)
        self.assertEqual(b'ok', f.read())

        self.webapp.unregister_path('/custom')
        self.assertRaises(urllib.error.HTTPError, urllib.request.urlopen, req)

    @skip("This returns a 500")
    def test_web_404_on_unknown_tenant(self):
        req = urllib.request.Request(
            "http://localhost:{}/non-tenant/status.json".format(self.port))
        e = self.assertRaises(
            urllib.error.HTTPError, urllib.request.urlopen, req)
        self.assertEqual(404, e.code)
