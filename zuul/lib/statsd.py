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

from zuul.lib.config import get_default


def get_statsd_config(config):
    statsd_host = get_default(config, 'statsd', 'server')
    statsd_port = int(get_default(config, 'statsd', 'port', 8125))
    statsd_prefix = get_default(config, 'statsd', 'prefix')
    return (statsd_host, statsd_port, statsd_prefix)


def get_statsd(config):
    (statsd_host, statsd_port, statsd_prefix) = get_statsd_config(config)
    if statsd_host is None:
        return None
    import statsd
    return statsd.StatsClient(statsd_host, statsd_port, statsd_prefix)
