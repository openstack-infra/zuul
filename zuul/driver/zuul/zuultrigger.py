# Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
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
import voluptuous as v
from zuul.model import EventFilter
from zuul.trigger import BaseTrigger


class ZuulTrigger(BaseTrigger):
    name = 'zuul'
    log = logging.getLogger("zuul.ZuulTrigger")

    def __init__(self, connection, config=None):
        super(ZuulTrigger, self).__init__(connection, config)
        self._handle_parent_change_enqueued_events = False
        self._handle_project_change_merged_events = False

    def getEventFilters(self, trigger_conf):
        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        efilters = []
        for trigger in toList(trigger_conf):
            f = EventFilter(
                trigger=self,
                types=toList(trigger['event']),
                pipelines=toList(trigger.get('pipeline')),
                required_approvals=(
                    toList(trigger.get('require-approval'))
                ),
                reject_approvals=toList(
                    trigger.get('reject-approval')
                ),
            )
            efilters.append(f)

        return efilters


def getSchema():
    def toList(x):
        return v.Any([x], x)

    approval = v.Schema({'username': str,
                         'email-filter': str,
                         'email': str,
                         'older-than': str,
                         'newer-than': str,
                         }, extra=v.ALLOW_EXTRA)

    zuul_trigger = {
        v.Required('event'):
        toList(v.Any('parent-change-enqueued',
                     'project-change-merged')),
        'pipeline': toList(str),
        'require-approval': toList(approval),
        'reject-approval': toList(approval),
    }

    return zuul_trigger
