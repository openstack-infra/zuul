#!/usr/bin/env python
# Copyright 2017 Red Hat
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

import argparse
import os
import re
import sys
import yaml

from collections import defaultdict
from collections import OrderedDict

REPO_SRC_DIR = "~zuul/src/git.openstack.org/"


# Class copied from zuul/lib/conemapper.py with minor logging changes
class CloneMapper(object):

    def __init__(self, clonemap, projects):
        self.clonemap = clonemap
        self.projects = projects

    def expand(self, workspace):
        print("Workspace path set to: %s" % workspace)

        is_valid = True
        ret = OrderedDict()
        errors = []
        for project in self.projects:
            dests = []
            for mapping in self.clonemap:
                if re.match(r'^%s$' % mapping['name'], project):
                    # Might be matched more than one time
                    dests.append(
                        re.sub(mapping['name'], mapping['dest'], project))

            if len(dests) > 1:
                errors.append(
                    "Duplicate destinations for %s: %s." % (project, dests))
                is_valid = False
            elif len(dests) == 0:
                print("Using %s as destination (unmatched)" % project)
                ret[project] = [project]
            else:
                ret[project] = dests

        if not is_valid:
            raise Exception("Expansion errors: %s" % errors)

        print("Mapping projects to workspace...")
        for project, dest in ret.items():
            dest = os.path.normpath(os.path.join(workspace, dest[0]))
            ret[project] = dest
            print("  %s -> %s" % (project, dest))

        print("Checking overlap in destination directories...")
        check = defaultdict(list)
        for project, dest in ret.items():
            check[dest].append(project)

        dupes = dict((d, p) for (d, p) in check.items() if len(p) > 1)
        if dupes:
            raise Exception("Some projects share the same destination: %s",
                            dupes)

        print("Expansion completed.")
        return ret


def parseArgs():
    ZUUL_ENV_SUFFIXES = ('branch', 'ref', 'url', 'project', 'newrev')

    parser = argparse.ArgumentParser()

    # Ignored arguments
    parser.add_argument('-v', '--verbose', dest='verbose',
                        action='store_true', help='IGNORED')
    parser.add_argument('--color', dest='color', action='store_true',
                        help='IGNORED')
    parser.add_argument('--cache-dir', dest='cache_dir', help='IGNORED')
    parser.add_argument('git_base_url', help='IGNORED')
    parser.add_argument('--branch', help='IGNORED')
    parser.add_argument('--project-branch', nargs=1, action='append',
                        metavar='PROJECT=BRANCH', help='IGNORED')
    for zuul_suffix in ZUUL_ENV_SUFFIXES:
        env_name = 'ZUUL_%s' % zuul_suffix.upper()
        parser.add_argument(
            '--zuul-%s' % zuul_suffix, metavar='$' + env_name,
            help='IGNORED'
        )

    # Active arguments
    parser.add_argument('-m', '--map', dest='clone_map_file',
                        help='specify clone map file')
    parser.add_argument('--workspace', dest='workspace',
                        default=os.getcwd(),
                        help='where to clone repositories too')
    parser.add_argument('projects', nargs='+',
                        help='list of Gerrit projects to clone')

    return parser.parse_args()


def readCloneMap(clone_map):
    clone_map_file = os.path.expanduser(clone_map)
    if not os.path.exists(clone_map_file):
        raise Exception("Unable to read clone map file at %s." %
                        clone_map_file)
    clone_map_file = open(clone_map_file)
    clone_map = yaml.safe_load(clone_map_file).get('clonemap')
    return clone_map


def main():
    args = parseArgs()

    clone_map = []
    if args.clone_map_file:
        clone_map = readCloneMap(args.clone_map_file)

    mapper = CloneMapper(clone_map, args.projects)
    dests = mapper.expand(workspace=args.workspace)

    for project in args.projects:
        src = os.path.join(os.path.expanduser(REPO_SRC_DIR), project)
        dst = dests[project]

        # Remove the tail end of the path (since the copy operation will
        # automatically create that)
        d = dst.rstrip('/')
        d, base = os.path.split(d)
        if not os.path.exists(d):
            print("Creating %s" % d)
            os.makedirs(d)

        # Create hard link copy of the source directory
        cmd = "cp -al %s %s" % (src, dst)
        print("%s" % cmd)
        if os.system(cmd):
            print("Error executing: %s" % cmd)
            sys.exit(1)


if __name__ == "__main__":
    main()
