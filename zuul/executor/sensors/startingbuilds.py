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

from zuul.executor.sensors import SensorInterface


class StartingBuildsSensor(SensorInterface):
    log = logging.getLogger("zuul.executor.sensor.startingbuilds")

    def __init__(self, executor, max_load_avg):
        self.executor = executor
        self.max_starting_builds = max_load_avg * 2
        self.min_starting_builds = max(int(multiprocessing.cpu_count() / 2), 1)

    def _getStartingBuilds(self):
        starting_builds = 0
        for worker in self.executor.job_workers.values():
            if not worker.started:
                starting_builds += 1
        return starting_builds

    def _getRunningBuilds(self):
        return len(self.executor.job_workers)

    def _getPausedBuilds(self):
        paused_builds = 0
        for worker in self.executor.job_workers.values():
            if not worker.paused:
                paused_builds += 1
        return paused_builds

    def isOk(self):
        starting_builds = self._getStartingBuilds()
        max_starting_builds = max(
            self.max_starting_builds - self._getRunningBuilds(),
            self.min_starting_builds)

        if starting_builds >= max_starting_builds:
            return False, "too many starting builds {} >= {}".format(
                starting_builds, max_starting_builds)

        return True, "{} <= {}".format(starting_builds, max_starting_builds)

    def reportStats(self, statsd, base_key):
        statsd.gauge(base_key + '.paused_builds', self._getPausedBuilds())
        statsd.gauge(base_key + '.running_builds', self._getRunningBuilds())
        statsd.gauge(base_key + '.starting_builds', self._getStartingBuilds())
