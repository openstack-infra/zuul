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

import abc


class SensorInterface(object, metaclass=abc.ABCMeta):
    """The sensor interface used by the load governor

    A sensor which provides load indicators for managing the load
    on an executor.

    """

    @abc.abstractmethod
    def isOk(self):
        """Report if current load is ok for accepting new jobs.

        :returns: Bool, str: True if we can accept new jobs, otherwise False
                  and a string for the log
        :rtype: Bool, str
        """
        pass

    @abc.abstractmethod
    def reportStats(self, statsd, base_key):
        """Report statistics to statsd

        :param statsd: the statsd object to use for reporting
        :param base_key: the base key to use for reporting
        """
        pass
