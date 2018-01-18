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

import re

from zuul.model import EventFilter, TriggerEvent


class ZuulEventFilter(EventFilter):
    def __init__(self, trigger, types=[], pipelines=[]):
        EventFilter.__init__(self, trigger)

        self._types = types
        self._pipelines = pipelines
        self.types = [re.compile(x) for x in types]
        self.pipelines = [re.compile(x) for x in pipelines]

    def __repr__(self):
        ret = '<ZuulEventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._pipelines:
            ret += ' pipelines: %s' % ', '.join(self._pipelines)
        ret += '>'

        return ret

    def matches(self, event, change):
        # event types are ORed
        matches_type = False
        for etype in self.types:
            if etype.match(event.type):
                matches_type = True
        if self.types and not matches_type:
            return False

        # pipelines are ORed
        matches_pipeline = False
        for epipe in self.pipelines:
            if epipe.match(event.pipeline_name):
                matches_pipeline = True
        if self.pipelines and not matches_pipeline:
            return False

        return True


class ZuulTriggerEvent(TriggerEvent):
    def __init__(self):
        super(ZuulTriggerEvent, self).__init__()
        self.pipeline_name = None
