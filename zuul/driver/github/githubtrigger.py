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

import logging
import voluptuous as v
from zuul.model import EventFilter
from zuul.trigger import BaseTrigger


class GithubTrigger(BaseTrigger):
    name = 'github'
    log = logging.getLogger("zuul.trigger.GithubTrigger")

    def _toList(self, item):
        if not item:
            return []
        if isinstance(item, list):
            return item
        return [item]

    def getEventFilters(self, trigger_config):
        efilters = []
        for trigger in self._toList(trigger_config):
            types = trigger.get('event', None)
            actions = trigger.get('action')
            refs = trigger.get('refs')
            comments = self._toList(trigger.get('comment'))
            labels = trigger.get('label')
            unlabels = trigger.get('unlabel')
            f = EventFilter(trigger=self,
                            types=self._toList(types),
                            actions=self._toList(actions),
                            refs=self._toList(refs),
                            comments=self._toList(comments),
                            labels=self._toList(labels),
                            unlabels=self._toList(unlabels))
            efilters.append(f)

        return efilters

    def onPullRequest(self, payload):
        pass


def getSchema():
    def toList(x):
        return v.Any([x], x)

    github_trigger = {
        v.Required('event'):
            toList(v.Any('pull_request',
                         'push')),
        'action': toList(str),
        'ref': toList(str),
        'comment': toList(str),
        'label': toList(str),
        'unlabel': toList(str),
    }

    return github_trigger
