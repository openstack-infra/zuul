# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
# Copyright 2016 Red Hat, Inc.
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
import subprocess

from zuul.driver import (Driver, WrapperInterface)
from zuul.execution_context import BaseExecutionContext


class NullExecutionContext(BaseExecutionContext):
    log = logging.getLogger("zuul.NullExecutionContext")

    def getPopen(self, **kwargs):
        return subprocess.Popen


class NullwrapDriver(Driver, WrapperInterface):
    name = 'nullwrap'
    log = logging.getLogger("zuul.NullwrapDriver")

    def getExecutionContext(self, ro_paths=None, rw_paths=None, secrets=None):
        # The bubblewrap driver writes secrets to a tmpfs so that they
        # don't hit the disk (unless the kernel swaps the memory to
        # disk, which can be mitigated with encrypted swap).  We
        # haven't implemented similar functionality in nullwrap, so
        # for safety, raise an exception in that case.  If you are
        # interested in implementing this functionality, please
        # contact us on the mailing list.
        if secrets:
            raise NotImplementedError(
                "The nullwrap driver does not support the use of secrets. "
                "Consider using the bubblewrap driver instead.")
        return NullExecutionContext()
