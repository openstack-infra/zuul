# Copyright 2015 Red Hat, Inc.
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

"""
This module defines classes used in matching changes based on job
configuration.
"""

import re


class AbstractChangeMatcher(object):

    def __init__(self, regex):
        self._regex = regex
        self.regex = re.compile(regex)

    def matches(self, change):
        """Return a boolean indication of whether change matches
        implementation-specific criteria.
        """
        raise NotImplementedError()

    def copy(self):
        return self.__class__(self._regex)

    def __deepcopy__(self, memo):
        return self.copy()

    def __eq__(self, other):
        return str(self) == str(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return '{%s:%s}' % (self.__class__.__name__, self._regex)

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self._regex)


class ProjectMatcher(AbstractChangeMatcher):

    def matches(self, change):
        return self.regex.match(str(change.project))


class BranchMatcher(AbstractChangeMatcher):

    def matches(self, change):
        if hasattr(change, 'branch'):
            if self.regex.match(change.branch):
                return True
            return False
        if self.regex.match(change.ref):
            return True
        return False


class ImpliedBranchMatcher(AbstractChangeMatcher):
    """
    A branch matcher that only considers branch refs, and always
    succeeds on other types (e.g., tags).
    """

    def matches(self, change):
        if hasattr(change, 'branch'):
            if self.regex.match(change.branch):
                return True
            return False
        return True


class FileMatcher(AbstractChangeMatcher):

    def matches(self, change):
        if not hasattr(change, 'files'):
            return False
        for file_ in change.files:
            if self.regex.match(file_):
                return True
        return False


class AbstractMatcherCollection(AbstractChangeMatcher):

    def __init__(self, matchers):
        self.matchers = matchers

    def __eq__(self, other):
        return str(self) == str(other)

    def __str__(self):
        return '{%s:%s}' % (self.__class__.__name__,
                            ','.join([str(x) for x in self.matchers]))

    def __repr__(self):
        return '<%s>' % self.__class__.__name__

    def copy(self):
        return self.__class__(self.matchers[:])


class MatchAllFiles(AbstractMatcherCollection):

    commit_regex = re.compile('^/COMMIT_MSG$')

    @property
    def regexes(self):
        for matcher in self.matchers:
            yield matcher.regex
        yield self.commit_regex

    def matches(self, change):
        if not (hasattr(change, 'files') and change.files):
            return False
        if len(change.files) == 1 and self.commit_regex.match(change.files[0]):
            return False
        for file_ in change.files:
            matched_file = False
            for regex in self.regexes:
                if regex.match(file_):
                    matched_file = True
                    break
            if not matched_file:
                return False
        return True


class MatchAll(AbstractMatcherCollection):

    def matches(self, change):
        for matcher in self.matchers:
            if not matcher.matches(change):
                return False
        return True


class MatchAny(AbstractMatcherCollection):

    def matches(self, change):
        for matcher in self.matchers:
            if matcher.matches(change):
                return True
        return False
