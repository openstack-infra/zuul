#!/usr/bin/env python
# Copyright 2019 BMW Group
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
import zuul.cmd
from zuul.lib.ansible import AnsibleManager


class ManageAnsible(zuul.cmd.ZuulApp):

    app_name = 'manage-ansible'
    app_description = 'Zuul ansible maager'
    log = logging.getLogger('zuul.ManageAnsible')

    def createParser(self):
        parser = super().createParser()
        parser.add_argument('-v', dest='verbose', action='store_true',
                            help='verbose output')
        parser.add_argument('-u', dest='upgrade', action='store_true',
                            help='upgrade ansible versions')
        return parser

    def _setup_logging(self):
        """Manage ansible logging does not rely on conf file"""
        if self.args.verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

    def main(self):
        self.parseArguments()
        try:
            self.readConfig()
        except Exception:
            # This script must be able to run without config so this can be
            # safely ignored here.
            pass
        self._setup_logging()

        manager = AnsibleManager()

        manager.install(upgrade=self.args.upgrade)


def main():
    ManageAnsible().main()


if __name__ == "__main__":
    main()
