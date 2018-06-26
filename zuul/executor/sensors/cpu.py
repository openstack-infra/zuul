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
import multiprocessing
import os

from zuul.executor.sensors import SensorInterface
from zuul.lib.config import get_default


class CPUSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.cpu")

    def __init__(self, config=None):
        load_multiplier = float(get_default(config, 'executor',
                                            'load_multiplier', '2.5'))
        self.max_load_avg = multiprocessing.cpu_count() * load_multiplier

    def isOk(self):
        load_avg = os.getloadavg()[0]

        if load_avg > self.max_load_avg:
            return False, "high system load {} > {}".format(
                load_avg, self.max_load_avg)

        return True, "{} <= {}".format(load_avg, self.max_load_avg)

    def reportStats(self, statsd, base_key):
        load_avg = os.getloadavg()[0]
        statsd.gauge(base_key + '.load_average', int(load_avg * 100))
