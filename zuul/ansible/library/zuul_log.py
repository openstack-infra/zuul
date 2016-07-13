#!/usr/bin/python

# Copyright (c) 2016 IBM Corp.
# Copyright (c) 2016 Red Hat
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

import datetime


class Console(object):
    def __enter__(self):
        self.logfile = open('/tmp/console.html', 'a', 0)
        return self

    def __exit__(self, etype, value, tb):
        self.logfile.close()

    def addLine(self, ln):
        ts = datetime.datetime.now()
        outln = '%s | %s' % (str(ts), ln)
        self.logfile.write(outln)


def log(msg):
    if not isinstance(msg, list):
        msg = [msg]
    with Console() as console:
        for line in msg:
            console.addLine("[Zuul] %s\n" % line)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            msg=dict(required=True, type='raw'),
        )
    )

    p = module.params
    log(p['msg'])
    module.exit_json(changed=True)

from ansible.module_utils.basic import *  # noqa

if __name__ == '__main__':
    main()
