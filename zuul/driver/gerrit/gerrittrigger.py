# Copyright 2012 Hewlett-Packard Development Company, L.P.
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
from zuul.driver.gerrit.gerritmodel import GerritEventFilter
from zuul.driver.util import scalar_or_list, to_list


class GerritTrigger(BaseTrigger):
    name = 'gerrit'
    log = logging.getLogger("zuul.GerritTrigger")

    def getEventFilters(self, trigger_conf):
        efilters = []
        for trigger in to_list(trigger_conf):
            approvals = {}
            for approval_dict in to_list(trigger.get('approval')):
                for key, val in approval_dict.items():
                    approvals[key] = val
            # Backwards compat for *_filter versions of these args
            comments = to_list(trigger.get('comment'))
            if not comments:
                comments = to_list(trigger.get('comment_filter'))
            emails = to_list(trigger.get('email'))
            if not emails:
                emails = to_list(trigger.get('email_filter'))
            usernames = to_list(trigger.get('username'))
            if not usernames:
                usernames = to_list(trigger.get('username_filter'))
            ignore_deletes = trigger.get('ignore-deletes', True)
            f = GerritEventFilter(
                trigger=self,
                types=to_list(trigger['event']),
                branches=to_list(trigger.get('branch')),
                refs=to_list(trigger.get('ref')),
                event_approvals=approvals,
                comments=comments,
                emails=emails,
                usernames=usernames,
                required_approvals=(
                    to_list(trigger.get('require-approval'))
                ),
                reject_approvals=to_list(
                    trigger.get('reject-approval')
                ),
                ignore_deletes=ignore_deletes
            )
            efilters.append(f)

        return efilters


def getSchema():
    variable_dict = v.Schema(dict)

    approval = v.Schema({'username': str,
                         'email': str,
                         'older-than': str,
                         'newer-than': str,
                         }, extra=v.ALLOW_EXTRA)

    gerrit_trigger = {
        v.Required('event'):
            scalar_or_list(v.Any('patchset-created',
                                 'draft-published',
                                 'change-abandoned',
                                 'change-restored',
                                 'change-merged',
                                 'comment-added',
                                 'ref-updated')),
        'comment_filter': scalar_or_list(str),
        'comment': scalar_or_list(str),
        'email_filter': scalar_or_list(str),
        'email': scalar_or_list(str),
        'username_filter': scalar_or_list(str),
        'username': scalar_or_list(str),
        'branch': scalar_or_list(str),
        'ref': scalar_or_list(str),
        'ignore-deletes': bool,
        'approval': scalar_or_list(variable_dict),
        'require-approval': scalar_or_list(approval),
        'reject-approval': scalar_or_list(approval),
    }

    return gerrit_trigger
