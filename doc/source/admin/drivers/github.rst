:title: GitHub Driver

GitHub
======

The GitHub driver supports sources, triggers, and reporters.  It can
interact with the public GitHub service as well as site-local
installations of GitHub enterprise.

.. TODO: make this section more user friendly

Configure GitHub `webhook events
<https://developer.github.com/webhooks/creating/>`_.

Set *Payload URL* to
``http://<zuul-hostname>/connection/<connection-name>/payload``.

Set *Content Type* to ``application/json``.

Select *Events* you are interested in. See below for the supported events.

Connection Configuration
------------------------

The supported options in zuul.conf connections are:

**driver=github**

**api_token**
  API token for accessing GitHub.
  See `Creating an access token for command-line use
  <https://help.github.com/articles/creating-an-access-token-for-command-line-use/>`_.

**webhook_token**
  Optional: Token for validating the webhook event payloads.
  If not specified, payloads are not validated.
  See `Securing your webhooks
  <https://developer.github.com/webhooks/securing/>`_.

**sshkey**
  Path to SSH key to use when cloning github repositories.
  ``sshkey=/home/zuul/.ssh/id_rsa``

**git_host**
  Optional: Hostname of the github install (such as a GitHub Enterprise)
  If not specified, defaults to ``github.com``
  ``git_host=github.myenterprise.com``

**canonical_hostname**
  The canonical hostname associated with the git repos on the GitHub
  server.  Defaults to the value of **git_host**.  This is used to
  identify repos from this connection by name and in preparing repos
  on the filesystem for use by jobs.  This only needs to be set in the
  case where the canonical public location of the git repos is not the
  same as the GitHub server and it would be incorrect to refer to
  those repos in configuration and build scripts using the GitHub
  server hostname.
  ``canonical_hostname=git.example.com``

Trigger Configuration
---------------------
GitHub webhook events can be configured as triggers.

A connection name with the github driver can take multiple events with the
following options.

**event**
  The event from github. Supported events are ``pull_request``,
  ``pull_request_review``, and ``push``.

  A ``pull_request`` event will have associated action(s) to trigger
  from. The supported actions are:

    *opened* - pull request opened

    *changed* - pull request synchronized

    *closed* - pull request closed

    *reopened* - pull request reopened

    *comment* - comment added on pull request

    *labeled* - label added on pull request

    *unlabeled* - label removed from pull request

    *status* - status set on commit

  A ``pull_request_review`` event will
  have associated action(s) to trigger from. The supported actions are:

    *submitted* - pull request review added

    *dismissed* - pull request review removed

**branch**
  The branch associated with the event. Example: ``master``.  This
  field is treated as a regular expression, and multiple branches may
  be listed. Used for ``pull_request`` and ``pull_request_review``
  events.

**comment**
  This is only used for ``pull_request`` ``comment`` actions.  It
  accepts a list of regexes that are searched for in the comment
  string. If any of these regexes matches a portion of the comment
  string the trigger is matched.  ``comment: retrigger`` will match
  when comments containing 'retrigger' somewhere in the comment text
  are added to a pull request.

**label**
  This is only used for ``labeled`` and ``unlabeled`` ``pull_request``
  actions.  It accepts a list of strings each of which matches the
  label name in the event literally.  ``label: recheck`` will match a
  ``labeled`` action when pull request is labeled with a ``recheck``
  label. ``label: 'do not test'`` will match a ``unlabeled`` action
  when a label with name ``do not test`` is removed from the pull
  request.

**state**
  This is only used for ``pull_request_review`` events.  It accepts a
  list of strings each of which is matched to the review state, which
  can be one of ``approved``, ``comment``, or ``request_changes``.

**status**
  This is used for ``pull-request`` and ``status`` actions. It accepts
  a list of strings each of which matches the user setting the status,
  the status context, and the status itself in the format of
  ``user:context:status``.  For example,
  ``zuul_github_ci_bot:check_pipeline:success``.

**ref**
  This is only used for ``push`` events. This field is treated as a
  regular expression and multiple refs may be listed. GitHub always
  sends full ref name, eg. ``refs/tags/bar`` and this string is
  matched against the regexp.

Reporter Configuration
----------------------
Zuul reports back to GitHub via GitHub API. Available reports include a PR
comment containing the build results, a commit status on start, success and
failure, an issue label addition/removal on the PR, and a merge of the PR
itself. Status name, description, and context is taken from the pipeline.

A :ref:`connection<connections>` that uses the github driver must be
supplied to the reporter. It has the following options:

**status**
  String value (``pending``, ``success``, ``failure``) that the
  reporter should set as the commit status on github.  ``status:
  'success'``

**status-url**
  String value for a link url to set in the github status. Defaults to
  the zuul server status_url, or the empty string if that is unset.

**comment**
  Boolean value (``true`` or ``false``) that determines if the
  reporter should add a comment to the pipeline status to the github
  pull request. Defaults to ``true``. Only used for Pull Request based
  events.  ``comment: false``

**merge**
  Boolean value (``true`` or ``false``) that determines if the
  reporter should merge the pull reqeust. Defaults to ``false``. Only
  used for Pull Request based events.  ``merge=true``

**label**
  List of strings each representing an exact label name which should
  be added to the pull request by reporter. Only used for Pull Request
  based events.  ``label: 'test successful'``

**unlabel**
  List of strings each representing an exact label name which should
  be removed from the pull request by reporter. Only used for Pull
  Request based events.  ``unlabel: 'test failed'``
