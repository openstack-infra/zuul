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

import os

from zuul.lib import yamlutil as yaml

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')
CONFIG_DIR = os.path.join(FIXTURE_DIR, 'config')


def make_playbook(path):
    d = os.path.dirname(path)
    try:
        os.makedirs(d)
    except OSError:
        pass
    with open(path, 'w') as f:
        f.write('- hosts: all\n')
        f.write('  tasks: []\n')


def handle_repo(path):
    print('Repo: %s' % path)
    config_path = None
    for fn in ['zuul.yaml', '.zuul.yaml']:
        if os.path.exists(os.path.join(path, fn)):
            config_path = os.path.join(path, fn)
            break
    try:
        config = yaml.safe_load(open(config_path))
    except Exception:
        print("  Has yaml errors")
        return
    for block in config:
        if 'job' not in block:
            continue
        job = block['job']['name']
        playbook = os.path.join(path, 'playbooks', job + '.yaml')
        if not os.path.exists(playbook):
            print('  Creating: %s' % job)
            make_playbook(playbook)


def main():
    repo_dirs = []

    for root, dirs, files in os.walk(CONFIG_DIR):
        if 'zuul.yaml' in files or '.zuul.yaml' in files:
            repo_dirs.append(root)

    for path in repo_dirs:
        handle_repo(path)


if __name__ == '__main__':
    main()
