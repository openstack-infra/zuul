# Copyright 2018 BMW Car IT GmbH
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

from zuul.executor.sensors import SensorInterface


class PauseSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.pause")

    def __init__(self):
        self.pause = False

    def isOk(self):
        if self.pause:
            return False, 'paused'
        else:
            return True, 'running'

    def reportStats(self, statsd, base_key):
        if self.pause:
            value = 1
        else:
            value = 0
        statsd.gauge(base_key + '.pause', value)
