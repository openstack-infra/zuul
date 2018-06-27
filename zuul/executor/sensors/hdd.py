# Copyright 2018 Red Hat, Inc.
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
import os

from zuul.executor.sensors import SensorInterface
from zuul.lib.config import get_default


def get_avail_hdd_pct(path):
    s = os.statvfs(path)
    used = float(s.f_blocks - s.f_bfree)
    percent = (used / s.f_blocks) * 100

    return (100.0 - percent)


class HDDSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.hdd")

    def __init__(self, config=None):
        self.min_avail_hdd = float(
            get_default(config, 'executor', 'min_avail_hdd', '5.0'))
        self.state_dir = get_default(
            config, 'executor', 'state_dir', '/var/lib/zuul', expand_user=True)

    def isOk(self):
        avail_hdd_pct = get_avail_hdd_pct(self.state_dir)

        if avail_hdd_pct < self.min_avail_hdd:
            return False, "low disk space {:3.1f}% < {}".format(
                avail_hdd_pct, self.min_avail_hdd)

        return True, "{:3.1f}% <= {}".format(avail_hdd_pct, self.min_avail_hdd)

    def reportStats(self, statsd, base_key):
        avail_hdd_pct = get_avail_hdd_pct(self.state_dir)

        # We multiply the percentage by 100 so we can report it to 2 decimal
        # points.
        statsd.gauge(base_key + '.pct_used_hdd',
                     int((100.0 - avail_hdd_pct) * 100))
