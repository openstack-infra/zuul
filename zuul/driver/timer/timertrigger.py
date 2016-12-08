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

import voluptuous as v

from zuul.model import EventFilter
from zuul.trigger import BaseTrigger


class TimerTrigger(BaseTrigger):
    name = 'timer'

    def getEventFilters(self, trigger_conf):
        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        efilters = []
        for trigger in toList(trigger_conf):
            f = EventFilter(trigger=self,
                            types=['timer'],
                            timespecs=toList(trigger['time']))

            efilters.append(f)

        return efilters


def getSchema():
    timer_trigger = {v.Required('time'): str}
    return timer_trigger
