# Copyright 2015 Rackspace Australia
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


class ChangeNotFound(Exception):
    def __init__(self, number, ps):
        self.number = number
        self.ps = ps
        self.change = "%s,%s" % (str(number), str(ps))
        message = "Change %s not found" % self.change
        super(ChangeNotFound, self).__init__(message)


class RevNotFound(Exception):
    def __init__(self, project, rev):
        self.project = project
        self.revision = rev
        message = ("Failed to checkout project '%s' at revision '%s'"
                   % (self.project, self.revision))
        super(RevNotFound, self).__init__(message)


class MergeFailure(Exception):
    pass


class ConfigurationError(Exception):
    pass
