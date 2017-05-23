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
from zuul.trigger import BaseTrigger
from zuul.driver.github.githubmodel import GithubEventFilter


class GithubTrigger(BaseTrigger):
    name = 'github'
    log = logging.getLogger("zuul.trigger.GithubTrigger")

    def getEventFilters(self, trigger_config):
        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        efilters = []
        for trigger in toList(trigger_config):
            f = GithubEventFilter(
                trigger=self,
                types=toList(trigger['event']),
                actions=toList(trigger.get('action')),
                branches=toList(trigger.get('branch')),
                refs=toList(trigger.get('ref')),
                comments=toList(trigger.get('comment')),
                labels=toList(trigger.get('label')),
                unlabels=toList(trigger.get('unlabel')),
                states=toList(trigger.get('state'))
            )
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
                         'pull_request_review',
                         'push')),
        'action': toList(str),
        'branch': toList(str),
        'ref': toList(str),
        'comment': toList(str),
        'label': toList(str),
        'unlabel': toList(str),
        'state': toList(str),
    }

    return github_trigger
