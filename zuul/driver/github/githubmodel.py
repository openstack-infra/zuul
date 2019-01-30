# Copyright 2015 Hewlett-Packard Development Company, L.P.
# Copyright 2017 IBM Corp.
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
import re2
import time

from zuul.model import Change, TriggerEvent, EventFilter, RefFilter
from zuul.driver.util import time_to_seconds


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes


class PullRequest(Change):
    def __init__(self, project):
        super(PullRequest, self).__init__(project)
        self.project = None
        self.pr = None
        self.updated_at = None
        self.title = None
        self.reviews = []
        self.files = []
        self.labels = []

    def isUpdateOf(self, other):
        if (self.project == other.project and
            hasattr(other, 'number') and self.number == other.number and
            hasattr(other, 'patchset') and self.patchset != other.patchset and
            hasattr(other, 'updated_at') and
            self.updated_at > other.updated_at):
            return True
        return False


class GithubTriggerEvent(TriggerEvent):
    def __init__(self):
        super(GithubTriggerEvent, self).__init__()
        self.title = None
        self.label = None
        self.unlabel = None
        self.action = None
        self.delivery = None

    def isPatchsetCreated(self):
        if self.type == 'pull_request':
            return self.action in ['opened', 'changed']
        return False

    def isChangeAbandoned(self):
        if self.type == 'pull_request':
            return 'closed' == self.action
        return False

    def _repr(self):
        r = [super(GithubTriggerEvent, self)._repr()]
        if self.action:
            r.append(self.action)
        r.append(self.canonical_project_name)
        if self.change_number:
            r.append('%s,%s' % (self.change_number, self.patch_number))
        if self.delivery:
            r.append('delivery: %s' % self.delivery)
        return ' '.join(r)


class GithubCommonFilter(object):
    def __init__(self, required_reviews=[], required_statuses=[],
                 reject_reviews=[], reject_statuses=[]):
        self._required_reviews = copy.deepcopy(required_reviews)
        self._reject_reviews = copy.deepcopy(reject_reviews)
        self.required_reviews = self._tidy_reviews(self._required_reviews)
        self.reject_reviews = self._tidy_reviews(self._reject_reviews)
        self.required_statuses = required_statuses
        self.reject_statuses = reject_statuses

    def _tidy_reviews(self, reviews):
        for r in reviews:
            for k, v in r.items():
                if k == 'username':
                    r['username'] = re.compile(v)
                elif k == 'email':
                    r['email'] = re.compile(v)
                elif k == 'newer-than':
                    r[k] = time_to_seconds(v)
                elif k == 'older-than':
                    r[k] = time_to_seconds(v)
        return reviews

    def _match_review_required_review(self, rreview, review):
        # Check if the required review and review match
        now = time.time()
        by = review.get('by', {})
        for k, v in rreview.items():
            if k == 'username':
                if (not v.search(by.get('username', ''))):
                    return False
            elif k == 'email':
                if (not v.search(by.get('email', ''))):
                    return False
            elif k == 'newer-than':
                t = now - v
                if (review['grantedOn'] < t):
                    return False
            elif k == 'older-than':
                t = now - v
                if (review['grantedOn'] >= t):
                    return False
            elif k == 'type':
                if review['type'] != v:
                    return False
            elif k == 'permission':
                # If permission is read, we've matched. You must have read
                # to provide a review.
                if v != 'read':
                    # Admins have implicit write.
                    if v == 'write':
                        if review['permission'] not in ('write', 'admin'):
                            return False
                    elif v == 'admin':
                        if review['permission'] != 'admin':
                            return False
        return True

    def matchesReviews(self, change):
        if self.required_reviews or self.reject_reviews:
            if not hasattr(change, 'number'):
                # not a PR, no reviews
                return False
            if self.required_reviews and not change.reviews:
                # No reviews means no matching of required bits
                # having reject reviews but no reviews on the change is okay
                return False

        return (self.matchesRequiredReviews(change) and
                self.matchesNoRejectReviews(change))

    def matchesRequiredReviews(self, change):
        for rreview in self.required_reviews:
            matches_review = False
            for review in change.reviews:
                if self._match_review_required_review(rreview, review):
                    # Consider matched if any review matches
                    matches_review = True
                    break
            if not matches_review:
                return False
        return True

    def matchesNoRejectReviews(self, change):
        for rreview in self.reject_reviews:
            for review in change.reviews:
                if self._match_review_required_review(rreview, review):
                    # A review matched, we can reject right away
                    return False
        return True

    def matchesStatuses(self, change):
        if self.required_statuses or self.reject_statuses:
            if not hasattr(change, 'number'):
                # not a PR, no status
                return False
            if self.required_statuses and not change.status:
                return False
        return (self.matchesRequiredStatuses(change) and
                self.matchesNoRejectStatuses(change))

    def matchesRequiredStatuses(self, change):
        # statuses are ORed
        # A PR head can have multiple statuses on it. If the change
        # statuses and the filter statuses are a null intersection, there
        # are no matches and we return false
        if self.required_statuses:
            for required_status in self.required_statuses:
                for status in change.status:
                    if re2.fullmatch(required_status, status):
                        return True
            return False
        return True

    def matchesNoRejectStatuses(self, change):
        # statuses are ANDed
        # If any of the rejected statusses are present, we return false
        for rstatus in self.reject_statuses:
            for status in change.status:
                if re2.fullmatch(rstatus, status):
                    return False
        return True


class GithubEventFilter(EventFilter, GithubCommonFilter):
    def __init__(self, trigger, types=[], branches=[], refs=[],
                 comments=[], actions=[], labels=[], unlabels=[],
                 states=[], statuses=[], required_statuses=[],
                 ignore_deletes=True):

        EventFilter.__init__(self, trigger)

        GithubCommonFilter.__init__(self, required_statuses=required_statuses)

        self._types = types
        self._branches = branches
        self._refs = refs
        self._comments = comments
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comments = [re.compile(x) for x in comments]
        self.actions = actions
        self.labels = labels
        self.unlabels = unlabels
        self.states = states
        self.statuses = statuses
        self.required_statuses = required_statuses
        self.ignore_deletes = ignore_deletes

    def __repr__(self):
        ret = '<GithubEventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.ignore_deletes:
            ret += ' ignore_deletes: %s' % self.ignore_deletes
        if self._comments:
            ret += ' comments: %s' % ', '.join(self._comments)
        if self.actions:
            ret += ' actions: %s' % ', '.join(self.actions)
        if self.labels:
            ret += ' labels: %s' % ', '.join(self.labels)
        if self.unlabels:
            ret += ' unlabels: %s' % ', '.join(self.unlabels)
        if self.states:
            ret += ' states: %s' % ', '.join(self.states)
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.required_statuses:
            ret += ' required_statuses: %s' % ', '.join(self.required_statuses)
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

        # actions are ORed
        matches_action = False
        for action in self.actions:
            if (event.action == action):
                matches_action = True
        if self.actions and not matches_action:
            return False

        # labels are ORed
        if self.labels and event.label not in self.labels:
            return False

        # unlabels are ORed
        if self.unlabels and event.unlabel not in self.unlabels:
            return False

        # states are ORed
        if self.states and event.state not in self.states:
            return False

        # statuses are ORed
        if self.statuses:
            status_found = False
            for status in self.statuses:
                if re2.fullmatch(status, event.status):
                    status_found = True
                    break
            if not status_found:
                return False

        if not self.matchesStatuses(change):
            return False

        return True


class GithubRefFilter(RefFilter, GithubCommonFilter):
    def __init__(self, connection_name, statuses=[], required_reviews=[],
                 reject_reviews=[], open=None, merged=None,
                 current_patchset=None, reject_open=None, reject_merged=None,
                 reject_current_patchset=None, labels=[], reject_labels=[],
                 reject_statuses=[]):
        RefFilter.__init__(self, connection_name)

        GithubCommonFilter.__init__(self, required_reviews=required_reviews,
                                    reject_reviews=reject_reviews,
                                    required_statuses=statuses,
                                    reject_statuses=reject_statuses)
        self.statuses = statuses
        if reject_open is not None:
            self.open = not reject_open
        else:
            self.open = open
        if reject_merged is not None:
            self.merged = not reject_merged
        else:
            self.merged = merged
        if reject_current_patchset is not None:
            self.current_patchset = not reject_current_patchset
        else:
            self.current_patchset = current_patchset
        self.labels = labels
        self.reject_labels = reject_labels

    def __repr__(self):
        ret = '<GithubRefFilter'

        ret += ' connection_name: %s' % self.connection_name
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.reject_statuses:
            ret += ' reject-statuses: %s' % ', '.join(self.reject_statuses)
        if self.required_reviews:
            ret += (' required-reviews: %s' %
                    str(self.required_reviews))
        if self.reject_reviews:
            ret += (' reject-reviews: %s' %
                    str(self.reject_reviews))
        if self.open:
            ret += ' open: %s' % self.open
        if self.merged:
            ret += ' merged: %s' % self.merged
        if self.current_patchset:
            ret += ' current-patchset: %s' % self.current_patchset
        if self.labels:
            ret += ' labels: %s' % self.labels
        if self.reject_labels:
            ret += ' reject-labels: %s' % self.reject_labels

        ret += '>'

        return ret

    def matches(self, change):
        if not self.matchesStatuses(change):
            return False

        if self.open is not None:
            # if a "change" has no number, it's not a change, but a push
            # and cannot possibly pass this test.
            if hasattr(change, 'number'):
                if self.open != change.open:
                    return False
            else:
                return False

        if self.merged is not None:
            # if a "change" has no number, it's not a change, but a push
            # and cannot possibly pass this test.
            if hasattr(change, 'number'):
                if self.merged != change.is_merged:
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

        # required reviews are ANDed (reject reviews are ORed)
        if not self.matchesReviews(change):
            return False

        # required labels are ANDed
        for label in self.labels:
            if label not in change.labels:
                return False

        # rejected reviews are OR'd
        for label in self.reject_labels:
            if label in change.labels:
                return False

        return True
