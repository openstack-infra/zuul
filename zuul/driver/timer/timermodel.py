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


class TimerEventFilter(EventFilter):
    def __init__(self, trigger, types=[], timespecs=[]):
        EventFilter.__init__(self, trigger)

        self._types = types
        self.types = [re.compile(x) for x in types]
        self.timespecs = timespecs

    def __repr__(self):
        ret = '<TimerEventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self.timespecs:
            ret += ' timespecs: %s' % ', '.join(self.timespecs)
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

        # timespecs are ORed
        matches_timespec = False
        for timespec in self.timespecs:
            if (event.timespec == timespec):
                matches_timespec = True
        if self.timespecs and not matches_timespec:
            return False

        return True


class TimerTriggerEvent(TriggerEvent):
    def __init__(self):
        super(TimerTriggerEvent, self).__init__()
        self.timespec = None
