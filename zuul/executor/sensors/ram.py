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
import psutil

from zuul.executor.sensors import SensorInterface
from zuul.lib.config import get_default


def get_avail_mem_pct():
    avail_mem_pct = 100.0 - psutil.virtual_memory().percent
    return avail_mem_pct


class RAMSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.ram")

    def __init__(self, config=None):
        self.min_avail_mem = float(get_default(config, 'executor',
                                               'min_avail_mem', '5.0'))

    def isOk(self):
        avail_mem_pct = get_avail_mem_pct()

        if avail_mem_pct < self.min_avail_mem:
            return False, "low memory {:3.1f}% < {}".format(
                avail_mem_pct, self.min_avail_mem)

        return True, "{:3.1f}% <= {}".format(avail_mem_pct, self.min_avail_mem)

    def reportStats(self, statsd, base_key):
        avail_mem_pct = get_avail_mem_pct()

        statsd.gauge(base_key + '.pct_used_ram',
                     int((100.0 - avail_mem_pct) * 100))
