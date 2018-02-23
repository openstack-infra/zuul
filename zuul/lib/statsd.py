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
from zuul.lib.config import get_default


def get_statsd_config(config):
    statsd_host = get_default(config, 'statsd', 'server')
    statsd_port = int(get_default(config, 'statsd', 'port', 8125))
    statsd_prefix = get_default(config, 'statsd', 'prefix')
    return (statsd_host, statsd_port, statsd_prefix)


def normalize_statsd_name(name):
    name = name.replace('.', '_')
    name = name.replace(':', '_')
    return name


def get_statsd(config, extra_keys=None):
    (statsd_host, statsd_port, statsd_prefix) = get_statsd_config(config)
    if statsd_host is None:
        return None
    import statsd

    class CustomStatsClient(statsd.StatsClient):

        def __init__(self, host, port, prefix, extra=None):
            self.extra_keys = copy.copy(extra) or {}

            for key in self.extra_keys:
                value = normalize_statsd_name(self.extra_keys[key])
                self.extra_keys[key] = value

            super().__init__(host, port, prefix)

        def _format_stat(self, name, **keys):
            format_keys = copy.copy(keys)

            # we need to normalize all keys which go into the metric name
            for key in format_keys.keys():
                normalized_value = normalize_statsd_name(format_keys[key])
                format_keys[key] = normalized_value

            format_keys.update(self.extra_keys)
            return name.format(**format_keys)

        def gauge(self, stat, value, rate=1, delta=False, **format_keys):
            stat = self._format_stat(stat, **format_keys)
            super().gauge(stat, value, rate, delta)

        def incr(self, stat, count=1, rate=1, **format_keys):
            stat = self._format_stat(stat, **format_keys)
            super().incr(stat, count, rate)

        def timing(self, stat, delta, rate=1, **format_keys):
            stat = self._format_stat(stat, **format_keys)
            super().timing(stat, delta, rate)

    return CustomStatsClient(
        statsd_host, statsd_port, statsd_prefix, extra_keys)
