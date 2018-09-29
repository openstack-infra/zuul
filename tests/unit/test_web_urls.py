# Copyright 2017 Red Hat, Inc.
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
import urllib

from bs4 import BeautifulSoup

from tests.base import ZuulTestCase, WebProxyFixture
from tests.base import ZuulWebFixture


class TestWebURLs(ZuulTestCase):
    tenant_config_file = 'config/single-tenant/main.yaml'

    def setUp(self):
        super(TestWebURLs, self).setUp()
        self.web = self.useFixture(
            ZuulWebFixture(self.gearman_server.port,
                           self.config))

    def _get(self, port, uri):
        url = "http://localhost:{}{}".format(port, uri)
        self.log.debug("GET {}".format(url))
        req = urllib.request.Request(url)
        try:
            f = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            raise Exception("Error on URL {}".format(url))
        return f.read()

    def _crawl(self, url):
        page = self._get(self.port, url)
        page = BeautifulSoup(page, 'html.parser')
        for (tag, attr) in [
                ('script', 'src'),
                ('link', 'href'),
                ('a', 'href'),
                ('img', 'src'),
        ]:
            for item in page.find_all(tag):
                suburl = item.get(attr)
                # Skip empty urls. Also skip the navbar relative link for now.
                # TODO(mordred) Remove when we have the top navbar link sorted.
                if suburl is None or suburl == "../":
                    continue
                link = urllib.parse.urljoin(url, suburl)
                self._get(self.port, link)


class TestDirect(TestWebURLs):
    # Test directly accessing the zuul-web server with no proxy
    def setUp(self):
        super(TestDirect, self).setUp()
        self.port = self.web.port

    def test_status_page(self):
        self._crawl('/t/tenant-one/status.html')


class TestWhiteLabel(TestWebURLs):
    # Test a zuul-web behind a whitelabel proxy (i.e., what
    # zuul.openstack.org does).
    def setUp(self):
        super(TestWhiteLabel, self).setUp()
        rules = [
            ('^/(.*)$', 'http://localhost:{}/\\1'.format(self.web.port)),
        ]
        self.proxy = self.useFixture(WebProxyFixture(rules))
        self.port = self.proxy.port

    def test_status_page(self):
        self._crawl('/status.html')


class TestWhiteLabelAPI(TestWebURLs):
    # Test a zuul-web behind a whitelabel proxy (i.e., what
    # zuul.openstack.org does).
    def setUp(self):
        super(TestWhiteLabelAPI, self).setUp()
        rules = [
            ('^/api/(.*)$',
             'http://localhost:{}/api/tenant/tenant-one/\\1'.format(
                 self.web.port)),
        ]
        self.proxy = self.useFixture(WebProxyFixture(rules))
        self.port = self.proxy.port

    def test_info(self):
        info = json.loads(self._get(self.port, '/api/info').decode('utf-8'))
        self.assertEqual('tenant-one', info['info']['tenant'])


class TestSuburl(TestWebURLs):
    # Test a zuul-web mounted on a suburl (i.e., what software factory
    # does).
    def setUp(self):
        super(TestSuburl, self).setUp()
        rules = [
            ('^/zuul3/(.*)$', 'http://localhost:{}/\\1'.format(
                self.web.port)),
        ]
        self.proxy = self.useFixture(WebProxyFixture(rules))
        self.port = self.proxy.port

    def test_status_page(self):
        self._crawl('/zuul3/t/tenant-one/status.html')
