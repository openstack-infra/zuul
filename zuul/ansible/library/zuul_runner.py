#!/usr/bin/python

# Copyright (c) 2016 IBM Corp.
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
import getpass
import os
import subprocess


class Console(object):
    def __enter__(self):
        self.logfile = open('/tmp/console.html', 'a', 0)
        return self

    def __exit__(self, etype, value, tb):
        self.logfile.close()

    def addLine(self, ln):
        ts = datetime.datetime.now()
        outln = '%s %s' % (str(ts), ln)
        self.logfile.write(outln)


def get_env():
    env = {}
    env['HOME'] = os.path.expanduser('~')
    env['USER'] = getpass.getuser()

    # Known locations for PAM mod_env sources
    for fn in ['/etc/environment', '/etc/default/locale']:
        if os.path.exists(fn):
            with open(fn) as f:
                for line in f:
                    k, v = line.strip().split('=')
                    env[k] = v
    return env


def run(cwd, cmd, args):
    env = get_env()
    env.update(args)
    proc = subprocess.Popen(
        ['/bin/bash', '-l', '-c', cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )

    with Console() as console:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            console.addLine(line)

        ret = proc.wait()
        console.addLine("[Zuul] Task exit code: %s\n" % ret)
    return ret


def main():
    module = AnsibleModule(
        argument_spec=dict(
            command=dict(required=True, default=None),
            cwd=dict(required=True, default=None),
            parameters=dict(default={}, type='dict')
        )
    )

    p = module.params
    env = p['parameters'].copy()
    ret = run(p['cwd'], p['command'], env)
    if ret == 0:
        module.exit_json(changed=True, rc=ret)
    else:
        module.fail_json(msg="Exit code %s" % ret, rc=ret)

from ansible.module_utils.basic import *  # noqa

if __name__ == '__main__':
    main()
