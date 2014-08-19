#!/usr/bin/env python
#
# Copyright 2014 Antoine "hashar" Musso
# Copyright 2014 Wikimedia Foundation Inc.
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
import logging
import os
import sys

import zuul.cmd
import zuul.lib.cloner

ZUUL_ENV_SUFFIXES = (
    'branch',
    'change',
    'patchset',
    'pipeline',
    'project',
    'ref',
    'url',
)


class Cloner(zuul.cmd.ZuulApp):
    log = logging.getLogger("zuul.Cloner")

    def parse_arguments(self):
        """Parse command line arguments and returns argparse structure"""
        parser = argparse.ArgumentParser(
            description='Zuul Project Gating System Cloner.')
        parser.add_argument('-m', '--map', dest='clone_map_file',
                            help='specifiy clone map file')
        parser.add_argument('--workspace', dest='workspace',
                            default=os.getcwd(),
                            help='where to clone repositories too')
        parser.add_argument('-v', '--verbose', dest='verbose',
                            action='store_true',
                            help='verbose output')
        parser.add_argument('--color', dest='color', action='store_true',
                            help='use color output')
        parser.add_argument('--version', dest='version', action='version',
                            version=self._get_version(),
                            help='show zuul version')
        parser.add_argument('--cache-dir', dest='cache_dir',
                            help=('a directory that holds cached copies of '
                                  'repos from which to make an initial clone.'
                                  ))
        parser.add_argument('git_base_url',
                            help='reference repo to clone from')
        parser.add_argument('projects', nargs='+',
                            help='list of Gerrit projects to clone')

        project_env = parser.add_argument_group(
            'project tuning'
        )
        project_env.add_argument(
            '--branch',
            help=('branch to checkout instead of Zuul selected branch, '
                  'for example to specify an alternate branch to test '
                  'client library compatibility.')
        )
        project_env.add_argument(
            '--project-branch', nargs=1, action='append',
            metavar='PROJECT=BRANCH',
            help=('project-specific branch to checkout which takes precedence '
                  'over --branch if it is provided; may be specified multiple '
                  'times.')
        )

        zuul_env = parser.add_argument_group(
            'zuul environnement',
            'Let you override $ZUUL_* environment variables.'
        )
        for zuul_suffix in ZUUL_ENV_SUFFIXES:
            env_name = 'ZUUL_%s' % zuul_suffix.upper()
            zuul_env.add_argument(
                '--zuul-%s' % zuul_suffix, metavar='$' + env_name,
                default=os.environ.get(env_name)
            )

        args = parser.parse_args()

        # Validate ZUUL_* arguments
        zuul_missing = [zuul_opt for zuul_opt, val in vars(args).items()
                        if zuul_opt.startswith('zuul') and val is None]
        if zuul_missing:
            parser.error(("Some Zuul parameters are not set:\n\t%s\n"
                          "Define them either via environment variables or "
                          "using options above." %
                          "\n\t".join(sorted(zuul_missing))))
        self.args = args

    def setup_logging(self, color=False, verbose=False):
        """Cloner logging does not rely on conf file"""
        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

        if color:
            # Color codes http://www.tldp.org/HOWTO/Bash-Prompt-HOWTO/x329.html
            logging.addLevelName(  # cyan
                logging.DEBUG, "\033[36m%s\033[0m" %
                logging.getLevelName(logging.DEBUG))
            logging.addLevelName(  # green
                logging.INFO, "\033[32m%s\033[0m" %
                logging.getLevelName(logging.INFO))
            logging.addLevelName(  # yellow
                logging.WARNING, "\033[33m%s\033[0m" %
                logging.getLevelName(logging.WARNING))
            logging.addLevelName(  # red
                logging.ERROR, "\033[31m%s\033[0m" %
                logging.getLevelName(logging.ERROR))
            logging.addLevelName(  # red background
                logging.CRITICAL, "\033[41m%s\033[0m" %
                logging.getLevelName(logging.CRITICAL))

    def main(self):
        self.parse_arguments()
        self.setup_logging(color=self.args.color, verbose=self.args.verbose)
        project_branches = {}
        if self.args.project_branch:
            for x in self.args.project_branch:
                project, branch = x[0].split('=')
                project_branches[project] = branch
        cloner = zuul.lib.cloner.Cloner(
            git_base_url=self.args.git_base_url,
            projects=self.args.projects,
            workspace=self.args.workspace,
            zuul_branch=self.args.zuul_branch,
            zuul_ref=self.args.zuul_ref,
            zuul_url=self.args.zuul_url,
            branch=self.args.branch,
            clone_map_file=self.args.clone_map_file,
            project_branches=project_branches,
            cache_dir=self.args.cache_dir,
        )
        cloner.execute()


def main():
    cloner = Cloner()
    cloner.main()


if __name__ == "__main__":
    sys.path.insert(0, '.')
    main()
