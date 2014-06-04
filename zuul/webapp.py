# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
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
import threading
import time
from paste import httpserver
import webob
from webob import dec


class WebApp(threading.Thread):
    log = logging.getLogger("zuul.WebApp")

    def __init__(self, scheduler, port=8001, cache_expiry=1):
        threading.Thread.__init__(self)
        self.scheduler = scheduler
        self.port = port
        self.cache_expiry = cache_expiry
        self.cache_time = 0
        self.cache = None
        self.daemon = True
        self.server = httpserver.serve(dec.wsgify(self.app), host='0.0.0.0',
                                       port=self.port, start_loop=False)

    def run(self):
        self.server.serve_forever()

    def stop(self):
        self.server.server_close()

    def app(self, request):
        if request.path != '/status.json':
            raise webob.exc.HTTPNotFound()
        if (not self.cache or
            (time.time() - self.cache_time) > self.cache_expiry):
            try:
                self.cache = self.scheduler.formatStatusJSON()
                # Call time.time() again because formatting above may take
                # longer than the cache timeout.
                self.cache_time = time.time()
            except:
                self.log.exception("Exception formatting status:")
                raise
        response = webob.Response(body=self.cache,
                                  content_type='application/json')
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
