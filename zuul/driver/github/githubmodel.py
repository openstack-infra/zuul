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
import time

from zuul.model import Change, TriggerEvent, EventFilter, RefFilter
from zuul.driver.util import time_to_seconds


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes


class PullRequest(Change):
    def __init__(self, project):
        super(PullRequest, self).__init__(project)
        self.updated_at = None
        self.title = None
        self.reviews = []

    def isUpdateOf(self, other):
        if (hasattr(other, 'number') and self.number == other.number and
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

    def isPatchsetCreated(self):
        if self.type == 'pull_request':
            return self.action in ['opened', 'changed']
        return False

    def isChangeAbandoned(self):
        if self.type == 'pull_request':
            return 'closed' == self.action
        return False


class GithubCommonFilter(object):
    def __init__(self, required_reviews=[], required_statuses=[]):
        self._required_reviews = copy.deepcopy(required_reviews)
        self.required_reviews = self._tidy_reviews(required_reviews)
        self.required_statuses = required_statuses

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
                # to provide a review. Write or admin permission is different.
                if v != 'read':
                    if review['permission'] != v:
                        return False
        return True

    def matchesReviews(self, change):
        if self.required_reviews and not change.reviews:
            # No reviews means no matching
            return False

        return self.matchesRequiredReviews(change)

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

    def matchesRequiredStatuses(self, change):
        # statuses are ORed
        # A PR head can have multiple statuses on it. If the change
        # statuses and the filter statuses are a null intersection, there
        # are no matches and we return false
        if self.required_statuses:
            if set(change.status).isdisjoint(set(self.required_statuses)):
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
        if self.statuses and event.status not in self.statuses:
            return False

        if not self.matchesRequiredStatuses(change):
            return False

        return True


class GithubRefFilter(RefFilter, GithubCommonFilter):
    def __init__(self, statuses=[], required_reviews=[]):
        RefFilter.__init__(self)

        GithubCommonFilter.__init__(self, required_reviews=required_reviews,
                                    required_statuses=statuses)
        self.statuses = statuses

    def __repr__(self):
        ret = '<GithubRefFilter'

        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.required_reviews:
            ret += (' required-reviews: %s' %
                    str(self.required_reviews))

        ret += '>'

        return ret

    def matches(self, change):
        if not self.matchesRequiredStatuses(change):
            return False

        # required reviews are ANDed
        if not self.matchesReviews(change):
            return False

        return True
