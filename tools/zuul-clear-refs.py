#!/usr/bin/env python
# Copyright 2014-2015 Antoine "hashar" Musso
# Copyright 2014-2015 Wikimedia Foundation Inc.
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

# pylint: disable=locally-disabled, invalid-name

"""
Zuul references cleaner.

Clear up references under /refs/zuul/ by inspecting the age of the commit the
reference points to.  If the commit date is older than a number of days
specificed by --until, the reference is deleted from the git repository.

Use --dry-run --verbose to finely inspect the script behavior.
"""

import argparse
import git
import logging
import time
import sys

NOW = int(time.time())
DEFAULT_DAYS = 360
ZUUL_REF_PREFIX = 'refs/zuul/'

parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument('--until', dest='days_ago', default=DEFAULT_DAYS, type=int,
                    help='references older than this number of day will '
                         'be deleted. Default: %s' % DEFAULT_DAYS)
parser.add_argument('-n', '--dry-run', dest='dryrun', action='store_true',
                    help='do not delete references')
parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                    help='set log level from info to debug')
parser.add_argument('gitrepo', help='path to a Zuul git repository')
args = parser.parse_args()

logging.basicConfig()
log = logging.getLogger('zuul-clear-refs')
if args.verbose:
    log.setLevel(logging.DEBUG)
else:
    log.setLevel(logging.INFO)

try:
    repo = git.Repo(args.gitrepo)
except git.exc.InvalidGitRepositoryError:
    log.error("Invalid git repo: %s" % args.gitrepo)
    sys.exit(1)

for ref in repo.references:

    if not ref.path.startswith(ZUUL_REF_PREFIX):
        continue
    if type(ref) is not git.refs.reference.Reference:
        # Paranoia: ignore heads/tags/remotes ..
        continue

    try:
        commit_ts = ref.commit.committed_date
    except LookupError:
        # GitPython does not properly handle PGP signed tags
        log.exception("Error in commit: %s, ref: %s. Type: %s",
                      ref.commit, ref.path, type(ref))
        continue

    commit_age = int((NOW - commit_ts) / 86400)  # days
    log.debug(
        "%s at %s is %3s days old",
        ref.commit,
        ref.path,
        commit_age,
    )
    if commit_age > args.days_ago:
        if args.dryrun:
            log.info("Would delete old ref: %s (%s)", ref.path, ref.commit)
        else:
            log.info("Deleting old ref: %s (%s)", ref.path, ref.commit)
            ref.delete(repo, ref.path)
