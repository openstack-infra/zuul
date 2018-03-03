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
import math
import psutil

from zuul.executor.sensors import SensorInterface
from zuul.lib.config import get_default

CGROUP_STATS_FILE = '/sys/fs/cgroup/memory/memory.stat'


def get_avail_mem_pct():
    avail_mem_pct = 100.0 - psutil.virtual_memory().percent
    return avail_mem_pct


class RAMSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.ram")

    def __init__(self, config=None):
        self.min_avail_mem = float(get_default(config, 'executor',
                                               'min_avail_mem', '5.0'))
        self.cgroup_stats_file = CGROUP_STATS_FILE

    def _read_cgroup_stat(self):
        stat = {}
        try:
            with open(self.cgroup_stats_file) as f:
                for line in f.readlines():
                    key, value = line.split(' ')
                    stat[key] = int(value.strip())
        except Exception:
            pass
        return stat

    def _get_cgroup_limit(self):
        stat = self._read_cgroup_stat()
        limit = stat.get('hierarchical_memory_limit', math.inf)
        mem_total = psutil.virtual_memory().total
        if limit < mem_total:
            return limit
        else:
            return math.inf

    def _get_avail_mem_pct_cgroup(self):
        stat = self._read_cgroup_stat()
        limit = stat.get('hierarchical_memory_limit', math.inf)
        usage = stat.get('total_rss', math.inf)

        if math.isinf(limit) or math.isinf(usage):
            # pretend we have all memory available if we got infs
            return 100

        return 100.0 - usage / limit * 100

    def isOk(self):
        avail_mem_pct = get_avail_mem_pct()

        if avail_mem_pct < self.min_avail_mem:
            return False, "low memory {:3.1f}% < {}".format(
                avail_mem_pct, self.min_avail_mem)

        if math.isinf(self._get_cgroup_limit()):
            # we have no cgroup defined limit so we're done now
            return True, "{:3.1f}% <= {}".format(
                avail_mem_pct, self.min_avail_mem)

        avail_mem_pct_cgroup = self._get_avail_mem_pct_cgroup()
        if avail_mem_pct_cgroup < self.min_avail_mem:
            return False, "low memory cgroup {:3.1f}% < {}".format(
                avail_mem_pct_cgroup, self.min_avail_mem)

        return True, "{:3.1f}% <= {}, {:3.1f}% <= {}".format(
            avail_mem_pct, self.min_avail_mem,
            avail_mem_pct_cgroup, self.min_avail_mem)

    def reportStats(self, statsd, base_key):
        avail_mem_pct = get_avail_mem_pct()

        statsd.gauge(base_key + '.pct_used_ram',
                     int((100.0 - avail_mem_pct) * 100))

        if math.isfinite(self._get_cgroup_limit()):
            avail_mem_pct_cgroup = self._get_avail_mem_pct_cgroup()
            statsd.gauge(base_key + '.pct_used_ram_cgroup',
                         int((100.0 - avail_mem_pct_cgroup) * 100))
