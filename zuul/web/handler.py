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

import abc
import os

from aiohttp import web


class BaseWebHandler(object, metaclass=abc.ABCMeta):

    def __init__(self, connection, zuul_web, method, path):
        self.connection = connection
        self.zuul_web = zuul_web
        self.method = method
        self.path = path

    @abc.abstractmethod
    async def handleRequest(self, request):
        """Process a web request."""


class BaseTenantWebHandler(BaseWebHandler):

    def __init__(self, connection, zuul_web, method, path):
        super(BaseTenantWebHandler, self).__init__(
            connection, zuul_web, method, '/api/tenant/{tenant}/' + path)


class BaseDriverWebHandler(BaseWebHandler):

    def __init__(self, connection, zuul_web, method, path):
        super(BaseDriverWebHandler, self).__init__(
            connection=connection, zuul_web=zuul_web, method=method, path=path)
        if path.startswith('/'):
            path = path[1:]
        self.path = '/api/connection/{connection}/{path}'.format(
            connection=self.connection.connection_name,
            path=path)


class StaticHandler(BaseWebHandler):

    def __init__(self, zuul_web, path, file_path=None):
        super(StaticHandler, self).__init__(None, zuul_web, 'GET', path)
        self.static_path = zuul_web.static_path
        self.file_path = file_path or path.split('/')[-1]

    async def handleRequest(self, request):
        """Process a web request."""
        headers = {}
        fp = os.path.join(self.static_path, self.file_path)
        if self.zuul_web.static_cache_expiry:
            headers['Cache-Control'] = "public, max-age=%d" % \
                self.zuul_web.static_cache_expiry
        return web.FileResponse(fp, headers=headers)
