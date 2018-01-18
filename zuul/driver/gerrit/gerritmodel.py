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

import copy
import re
import time

from zuul.model import EventFilter, RefFilter
from zuul.model import Change, TriggerEvent
from zuul.driver.util import time_to_seconds


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes


class GerritChange(Change):
    def __init__(self, project):
        super(GerritChange, self).__init__(project)
        self.approvals = []


class GerritTriggerEvent(TriggerEvent):
    """Incoming event from an external system."""
    def __init__(self):
        super(GerritTriggerEvent, self).__init__()
        self.approvals = []

    def __repr__(self):
        ret = '<GerritTriggerEvent %s %s' % (self.type,
                                             self.canonical_project_name)

        if self.branch:
            ret += " %s" % self.branch
        if self.change_number:
            ret += " %s,%s" % (self.change_number, self.patch_number)
        if self.approvals:
            ret += ' ' + ', '.join(
                ['%s:%s' % (a['type'], a['value']) for a in self.approvals])
        ret += '>'

        return ret

    def isPatchsetCreated(self):
        return 'patchset-created' == self.type

    def isChangeAbandoned(self):
        return 'change-abandoned' == self.type


class GerritApprovalFilter(object):
    def __init__(self, required_approvals=[], reject_approvals=[]):
        self._required_approvals = copy.deepcopy(required_approvals)
        self.required_approvals = self._tidy_approvals(
            self._required_approvals)
        self._reject_approvals = copy.deepcopy(reject_approvals)
        self.reject_approvals = self._tidy_approvals(self._reject_approvals)

    def _tidy_approvals(self, approvals):
        for a in approvals:
            for k, v in a.items():
                if k == 'username':
                    a['username'] = re.compile(v)
                elif k == 'email':
                    a['email'] = re.compile(v)
                elif k == 'newer-than':
                    a[k] = time_to_seconds(v)
                elif k == 'older-than':
                    a[k] = time_to_seconds(v)
        return approvals

    def _match_approval_required_approval(self, rapproval, approval):
        # Check if the required approval and approval match
        if 'description' not in approval:
            return False
        now = time.time()
        by = approval.get('by', {})
        for k, v in rapproval.items():
            if k == 'username':
                if (not v.search(by.get('username', ''))):
                        return False
            elif k == 'email':
                if (not v.search(by.get('email', ''))):
                        return False
            elif k == 'newer-than':
                t = now - v
                if (approval['grantedOn'] < t):
                        return False
            elif k == 'older-than':
                t = now - v
                if (approval['grantedOn'] >= t):
                    return False
            else:
                if not isinstance(v, list):
                    v = [v]
                if (approval['description'] != k or
                        int(approval['value']) not in v):
                    return False
        return True

    def matchesApprovals(self, change):
        if self.required_approvals or self.reject_approvals:
            if not hasattr(change, 'number'):
                # Not a change, no reviews
                return False
        if (self.required_approvals and not change.approvals
                or self.reject_approvals and not change.approvals):
            # A change with no approvals can not match
            return False

        # TODO(jhesketh): If we wanted to optimise this slightly we could
        # analyse both the REQUIRE and REJECT filters by looping over the
        # approvals on the change and keeping track of what we have checked
        # rather than needing to loop on the change approvals twice
        return (self.matchesRequiredApprovals(change) and
                self.matchesNoRejectApprovals(change))

    def matchesRequiredApprovals(self, change):
        # Check if any approvals match the requirements
        for rapproval in self.required_approvals:
            matches_rapproval = False
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # We have a matching approval so this requirement is
                    # fulfilled
                    matches_rapproval = True
                    break
            if not matches_rapproval:
                return False
        return True

    def matchesNoRejectApprovals(self, change):
        # Check to make sure no approvals match a reject criteria
        for rapproval in self.reject_approvals:
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # A reject approval has been matched, so we reject
                    # immediately
                    return False
        # To get here no rejects can have been matched so we should be good to
        # queue
        return True


class GerritEventFilter(EventFilter, GerritApprovalFilter):
    def __init__(self, trigger, types=[], branches=[], refs=[],
                 event_approvals={}, comments=[], emails=[], usernames=[],
                 required_approvals=[], reject_approvals=[],
                 ignore_deletes=True):

        EventFilter.__init__(self, trigger)

        GerritApprovalFilter.__init__(self,
                                      required_approvals=required_approvals,
                                      reject_approvals=reject_approvals)

        self._types = types
        self._branches = branches
        self._refs = refs
        self._comments = comments
        self._emails = emails
        self._usernames = usernames
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comments = [re.compile(x) for x in comments]
        self.emails = [re.compile(x) for x in emails]
        self.usernames = [re.compile(x) for x in usernames]
        self.event_approvals = event_approvals
        self.ignore_deletes = ignore_deletes

    def __repr__(self):
        ret = '<GerritEventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.ignore_deletes:
            ret += ' ignore_deletes: %s' % self.ignore_deletes
        if self.event_approvals:
            ret += ' event_approvals: %s' % ', '.join(
                ['%s:%s' % a for a in self.event_approvals.items()])
        if self.required_approvals:
            ret += ' required_approvals: %s' % ', '.join(
                ['%s' % a for a in self._required_approvals])
        if self.reject_approvals:
            ret += ' reject_approvals: %s' % ', '.join(
                ['%s' % a for a in self._reject_approvals])
        if self._comments:
            ret += ' comments: %s' % ', '.join(self._comments)
        if self._emails:
            ret += ' emails: %s' % ', '.join(self._emails)
        if self._usernames:
            ret += ' usernames: %s' % ', '.join(self._usernames)
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

        # branches are ORed
        matches_branch = False
        for branch in self.branches:
            if branch.match(event.branch):
                matches_branch = True
        if self.branches and not matches_branch:
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

        # comments are ORed
        matches_comment_re = False
        for comment_re in self.comments:
            if (event.comment is not None and
                comment_re.search(event.comment)):
                matches_comment_re = True
        if self.comments and not matches_comment_re:
            return False

        # We better have an account provided by Gerrit to do
        # email filtering.
        if event.account is not None:
            account_email = event.account.get('email')
            # emails are ORed
            matches_email_re = False
            for email_re in self.emails:
                if (account_email is not None and
                        email_re.search(account_email)):
                    matches_email_re = True
            if self.emails and not matches_email_re:
                return False

            # usernames are ORed
            account_username = event.account.get('username')
            matches_username_re = False
            for username_re in self.usernames:
                if (account_username is not None and
                    username_re.search(account_username)):
                    matches_username_re = True
            if self.usernames and not matches_username_re:
                return False

        # approvals are ANDed
        for category, value in self.event_approvals.items():
            matches_approval = False
            for eapp in event.approvals:
                if (eapp['description'] == category and
                        int(eapp['value']) == int(value)):
                    matches_approval = True
            if not matches_approval:
                return False

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
            return False

        return True


class GerritRefFilter(RefFilter, GerritApprovalFilter):
    def __init__(self, connection_name, open=None, current_patchset=None,
                 statuses=[], required_approvals=[],
                 reject_approvals=[]):
        RefFilter.__init__(self, connection_name)

        GerritApprovalFilter.__init__(self,
                                      required_approvals=required_approvals,
                                      reject_approvals=reject_approvals)

        self.open = open
        self.current_patchset = current_patchset
        self.statuses = statuses

    def __repr__(self):
        ret = '<GerritRefFilter'

        ret += ' connection_name: %s' % self.connection_name
        if self.open is not None:
            ret += ' open: %s' % self.open
        if self.current_patchset is not None:
            ret += ' current-patchset: %s' % self.current_patchset
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.required_approvals:
            ret += (' required-approvals: %s' %
                    str(self.required_approvals))
        if self.reject_approvals:
            ret += (' reject-approvals: %s' %
                    str(self.reject_approvals))
        ret += '>'

        return ret

    def matches(self, change):
        if self.open is not None:
            # if a "change" has no number, it's not a change, but a push
            # and cannot possibly pass this test.
            if hasattr(change, 'number'):
                if self.open != change.open:
                    return False
            else:
                return False

        if self.current_patchset is not None:
            # if a "change" has no number, it's not a change, but a push
            # and cannot possibly pass this test.
            if hasattr(change, 'number'):
                if self.current_patchset != change.is_current_patchset:
                    return False
            else:
                return False

        if self.statuses:
            if change.status not in self.statuses:
                return False

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
            return False

        return True
