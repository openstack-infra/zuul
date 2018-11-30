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

import gear
import logging

log = logging.getLogger("zuul.gear_utils")


def getGearmanFunctions(gearman):
    functions = {}
    for connection in gearman.active_connections:
        try:
            req = gear.StatusAdminRequest()
            connection.sendAdminRequest(req, timeout=300)
        except Exception:
            log.exception("Exception while listing functions")
            gearman._lostConnection(connection)
            continue
        for line in req.response.decode('utf8').split('\n'):
            parts = [x.strip() for x in line.split('\t')]
            if len(parts) < 4:
                continue
            # parts[0] - function name
            # parts[1] - total jobs queued (including building)
            # parts[2] - jobs building
            # parts[3] - workers registered
            data = functions.setdefault(parts[0], [0, 0, 0])
            for i in range(3):
                data[i] += int(parts[i + 1])
    return functions
