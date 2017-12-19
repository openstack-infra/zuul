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

from zuul.model import TriggerEvent
from zuul.model import EventFilter


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes


class GitTriggerEvent(TriggerEvent):
    """Incoming event from an external system."""

    def __repr__(self):
        ret = '<GitTriggerEvent %s %s' % (self.type,
                                          self.project_name)

        if self.branch:
            ret += " %s" % self.branch
        ret += " oldrev:%s" % self.oldrev
        ret += " newrev:%s" % self.newrev
        ret += '>'

        return ret


class GitEventFilter(EventFilter):
    def __init__(self, trigger, types=[], refs=[],
                 ignore_deletes=True):

        super().__init__(trigger)

        self._refs = refs
        self.types = types
        self.refs = [re.compile(x) for x in refs]
        self.ignore_deletes = ignore_deletes

    def __repr__(self):
        ret = '<GitEventFilter'

        if self.types:
            ret += ' types: %s' % ', '.join(self.types)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.ignore_deletes:
            ret += ' ignore_deletes: %s' % self.ignore_deletes
        ret += '>'

        return ret

    def matches(self, event, change):
        # event types are ORed
        matches_type = False
        for etype in self.types:
            if etype == event.type:
                matches_type = True
        if self.types and not matches_type:
            return False

        # refs are ORed
        matches_ref = False
        if event.ref is not None:
            for ref in self.refs:
                if ref.match(event.ref):
                    matches_ref = True
        if self.refs and not matches_ref:
            return False
        if self.ignore_deletes and event.newrev == EMPTY_GIT_REF:
            # If the updated ref has an empty git sha (all 0s),
            # then the ref is being deleted
            return False

        return True
