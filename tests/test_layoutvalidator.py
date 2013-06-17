#!/usr/bin/env python

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

import os
import re

import testtools
import voluptuous
import yaml

import zuul.layoutvalidator

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
LAYOUT_RE = re.compile(r'^(good|bad)_.*\.yaml$')


class testScheduler(testtools.TestCase):
    def test_layouts(self):
        """Test layout file validation"""
        print
        errors = []
        for fn in os.listdir(os.path.join(FIXTURE_DIR, 'layouts')):
            m = LAYOUT_RE.match(fn)
            if not m:
                continue
            print fn
            layout = os.path.join(FIXTURE_DIR, 'layouts', fn)
            data = yaml.load(open(layout))
            validator = zuul.layoutvalidator.LayoutValidator()
            if m.group(1) == 'good':
                try:
                    validator.validate(data)
                except voluptuous.Invalid, e:
                    raise Exception(
                        'Unexpected YAML syntax error in %s:\n  %s' %
                        (fn, str(e)))
            else:
                try:
                    validator.validate(data)
                    raise Exception("Expected a YAML syntax error in %s." %
                                    fn)
                except voluptuous.Invalid, e:
                    error = str(e)
                    print '  ', error
                    if error in errors:
                        raise Exception("Error has already beed tested: %s" %
                                        error)
                    else:
                        errors.append(error)
                    pass
