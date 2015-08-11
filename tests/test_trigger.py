# Copyright 2014 Rackspace Australia
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
import testtools

import zuul.trigger


class TestGerritTrigger(testtools.TestCase):
    log = logging.getLogger("zuul.test_trigger")

    def test_trigger_abc(self):
        # We only need to instantiate a class for this
        zuul.trigger.gerrit.GerritTrigger({})

    def test_trigger_name(self):
        self.assertEqual('gerrit', zuul.trigger.gerrit.GerritTrigger.name)


class TestTimerTrigger(testtools.TestCase):
    log = logging.getLogger("zuul.test_trigger")

    def test_trigger_abc(self):
        # We only need to instantiate a class for this
        zuul.trigger.timer.TimerTrigger({})

    def test_trigger_name(self):
        self.assertEqual('timer', zuul.trigger.timer.TimerTrigger.name)


class TestZuulTrigger(testtools.TestCase):
    log = logging.getLogger("zuul.test_trigger")

    def test_trigger_abc(self):
        # We only need to instantiate a class for this
        zuul.trigger.zuultrigger.ZuulTrigger({})

    def test_trigger_name(self):
        self.assertEqual('zuul', zuul.trigger.zuultrigger.ZuulTrigger.name)
