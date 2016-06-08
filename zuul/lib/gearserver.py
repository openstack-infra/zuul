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

import gear

MASS_DO = 101


class GearServer(gear.Server):
    def handlePacket(self, packet):
        if packet.ptype == MASS_DO:
            self.log.info("Received packet from %s: %s" % (packet.connection,
                                                           packet))
            self.handleMassDo(packet)
        else:
            return super(GearServer, self).handlePacket(packet)

    def handleMassDo(self, packet):
        packet.connection.functions = set()
        for name in packet.data.split(b'\x00'):
            self.log.debug("Adding function %s to %s" % (
                name, packet.connection))
            packet.connection.functions.add(name)
            self.functions.add(name)
