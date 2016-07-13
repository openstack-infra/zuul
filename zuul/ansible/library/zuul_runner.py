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
import threading


class Console(object):
    def __enter__(self):
        self.logfile = open('/tmp/console.html', 'a', 0)
        return self

    def __exit__(self, etype, value, tb):
        self.logfile.close()

    def addLine(self, ln):
        # Note this format with deliminator is "inspired" by the old
        # Jenkins format but with microsecond resolution instead of
        # millisecond.  It is kept so log parsing/formatting remains
        # consistent.
        ts = datetime.datetime.now()
        outln = '%s | %s' % (ts, ln)
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
                    if not line:
                        continue
                    if line[0] == '#':
                        continue
                    if '=' not in line:
                        continue
                    k, v = line.strip().split('=')
                    for q in ["'", '"']:
                        if v[0] == q:
                            v = v.strip(q)
                    env[k] = v
    return env


def follow(fd):
    newline_warning = False
    with Console() as console:
        while True:
            line = fd.readline()
            if not line:
                break
            if not line.endswith('\n'):
                line += '\n'
                newline_warning = True
            console.addLine(line)
        if newline_warning:
            console.addLine('[Zuul] No trailing newline\n')


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

    t = threading.Thread(target=follow, args=(proc.stdout,))
    t.daemon = True
    t.start()

    ret = proc.wait()
    # Give the thread that is writing the console log up to 10 seconds
    # to catch up and exit.  If it hasn't done so by then, it is very
    # likely stuck in readline() because it spawed a child that is
    # holding stdout or stderr open.
    t.join(10)
    with Console() as console:
        if t.isAlive():
            console.addLine("[Zuul] standard output/error still open "
                            "after child exited")
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
