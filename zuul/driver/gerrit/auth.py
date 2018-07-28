# Copyright 2015 Christoph Gysin <christoph.gysin@gmail.com>
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
import requests

from urllib.parse import urlparse


class FormAuth(requests.auth.AuthBase):
    log = logging.getLogger('zuul.GerritConnection')

    def __init__(self, username, password):
        self.username = username
        self.password = password

    def _retry_using_form_auth(self, response, args):
        adapter = requests.adapters.HTTPAdapter()
        request = _copy_request(response.request)

        u = urlparse.urlparse(response.url)
        url = urlparse.urlunparse([u.scheme, u.netloc, '/login',
                                   None, None, None])
        auth = {'username': self.username,
                'password': self.password}
        request2 = requests.Request('POST', url, data=auth).prepare()
        response2 = adapter.send(request2, **args)

        if response2.status_code == 401:
            self.log.error('Login failed: Invalid username or password?')
            return response

        cookie = response2.headers.get('set-cookie')
        if cookie is not None:
            request.headers['Cookie'] = cookie

        response3 = adapter.send(request, **args)
        return response3

    def _response_hook(self, response, **kwargs):
        if response.status_code == 401:
            return self._retry_using_form_auth(response, kwargs)
        return response

    def __call__(self, request):
        request.headers["Connection"] = "Keep-Alive"
        request.register_hook('response', self._response_hook)
        return request


def _copy_request(request):
    new_request = requests.PreparedRequest()
    new_request.method = request.method
    new_request.url = request.url
    new_request.body = request.body
    new_request.hooks = request.hooks
    new_request.headers = request.headers.copy()
    return new_request
