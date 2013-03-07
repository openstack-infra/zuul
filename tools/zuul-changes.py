#!/usr/bin/env python
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

# Print commands to leave gerrit comments for every change in one of
# Zuul's pipelines.

import urllib2
import json
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('url', help='The URL of the running Zuul instance')
parser.add_argument('pipeline_name', help='The name of the Zuul pipeline')
parser.add_argument('comment', help='The text of the Gerrit comment')
parser.add_argument('--review-host', default='review',
                    help='The Gerrit hostname')
options = parser.parse_args()

data = urllib2.urlopen('%s/status.json' % options.url).read()
data = json.loads(data)

for pipeline in data['pipelines']:
    if pipeline['name'] != options.pipeline_name:
        continue
    for queue in pipeline['change_queues']:
        for head in queue['heads']:
            for change in head:
                print 'ssh %s gerrit review %s --message \\"%s\\"' % (
                    options.review_host,
                    change['id'],
                    options.comment)
