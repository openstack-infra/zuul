#!/usr/bin/env python

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

import argparse
import os
import sys

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
CONFIG_DIR = os.path.join(FIXTURE_DIR, 'config')


def print_file(title, path):
    print('')
    print(title)
    print('-' * 78)
    with open(path) as f:
        print(f.read())
    print('-' * 78)


def main():
    parser = argparse.ArgumentParser(description='Print test layout.')
    parser.add_argument(dest='config', nargs='?',
                        help='the test configuration name')
    args = parser.parse_args()
    if not args.config:
        print('Available test configurations:')
        for d in os.listdir(CONFIG_DIR):
            print('  ' + d)
        sys.exit(1)
    configdir = os.path.join(CONFIG_DIR, args.config)

    title = '   Configuration: %s   ' % args.config
    print('=' * len(title))
    print(title)
    print('=' * len(title))
    print_file('Main Configuration',
               os.path.join(configdir, 'main.yaml'))

    gitroot = os.path.join(configdir, 'git')
    for gitrepo in os.listdir(gitroot):
        reporoot = os.path.join(gitroot, gitrepo)
        print('')
        print('=== Git repo: %s ===' % gitrepo)
        filenames = os.listdir(reporoot)
        for fn in filenames:
            if fn in ['zuul.yaml', '.zuul.yaml']:
                print_file('File: ' + os.path.join(gitrepo, fn),
                           os.path.join(reporoot, fn))
        for subdir in ['.zuul.d', 'zuul.d']:
            zuuld = os.path.join(reporoot, subdir)
            if not os.path.exists(zuuld):
                continue
            filenames = os.listdir(zuuld)
            for fn in filenames:
                print_file('File: ' + os.path.join(gitrepo, subdir, fn),
                           os.path.join(zuuld, fn))


if __name__ == '__main__':
    main()
