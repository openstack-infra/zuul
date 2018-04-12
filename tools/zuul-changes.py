#!/usr/bin/env python
# Copyright 2013 OpenStack Foundation
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

import urllib2
import json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('url', help='The URL of the running Zuul instance')
parser.add_argument('tenant', help='The Zuul tenant')
parser.add_argument('pipeline', help='The name of the Zuul pipeline')
options = parser.parse_args()

# Check if tenant is white label
info = json.loads(urllib2.urlopen('%s/api/info' % options.url).read())
api_tenant = info.get('info', {}).get('tenant')
if api_tenant:
    if api_tenant == options.tenant:
        status_url = '%s/api/status' % options.url
    else:
        print("Error: %s doesn't match tenant %s (!= %s)" % (
            options.url, options.tenant, api_tenant))
        exit(1)
else:
    status_url = '%s/api/tenant/%s/status' % (options.url, options.tenant)

data = json.loads(urllib2.urlopen(status_url).read())

for pipeline in data['pipelines']:
    if pipeline['name'] != options.pipeline:
        continue
    for queue in pipeline['change_queues']:
        for head in queue['heads']:
            for change in head:
                if not change['live']:
                    continue
                cid, cps = change['id'].split(',')
                print(
                    "zuul enqueue --tenant %s --trigger gerrit "
                    "--pipeline %s --project %s --change %s,%s" % (
                        options.tenant,
                        options.pipeline,
                        change['project'],
                        cid, cps)
                )
