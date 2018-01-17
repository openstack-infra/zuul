#!/usr/bin/env python3

import logging

from zuul.driver.github.githubconnection import GithubConnection
from zuul.driver.github import GithubDriver
from zuul.model import Change, Project

# This is a template with boilerplate code for debugging github issues

# TODO: for real use override the following variables
server = 'github.com'
api_token = 'xxxx'

org = 'example'
repo = 'sandbox'
pull_nr = 8


def configure_logging(context):
    stream_handler = logging.StreamHandler()
    logger = logging.getLogger(context)
    logger.addHandler(stream_handler)
    logger.setLevel(logging.DEBUG)


# uncomment for more logging
# configure_logging('urllib3')
# configure_logging('github3')
# configure_logging('cachecontrol')


# This is all that's needed for getting a usable github connection
def create_connection(server, api_token):
    driver = GithubDriver()
    connection_config = {
        'server': server,
        'api_token': api_token,
    }
    conn = GithubConnection(driver, 'github', connection_config)
    conn._authenticateGithubAPI()
    return conn


def get_change(connection: GithubConnection,
               org: str,
               repo: str,
               pull: int) -> Change:
    p = Project("%s/%s" % (org, repo), connection.source)
    github = connection.getGithubClient(p)
    pr = github.pull_request(org, repo, pull)
    sha = pr.head.sha
    return conn._getChange(p, pull, sha, True)


# create github connection
conn = create_connection(server, api_token)


# Now we can do anything we want with the connection, e.g. check canMerge for
# a pull request.
change = get_change(conn, org, repo, pull_nr)

print(conn.canMerge(change, {'cc/gate2'}))


# Or just use the github object.
# github = conn.getGithubClient()
#
# repository = github.repository(org, repo)
# print(repository.as_dict())
