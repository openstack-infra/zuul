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

There are two forms of operation. Either the Zuul installation can be
configured as a `Github App`_ or it can be configured as a Webhook.

If the `Github App`_ approach is taken, the config settings ``app_id`` and
``app_key`` are required. If the Webhook approach is taken, the ``api_token``
setting is required.

The supported options in zuul.conf connections are:

**driver=github**

**app_id**
  App ID if you are using a GitHub App. Can be found under the "Public Link"
  on the right hand side labeled "ID".
  ``app_id=1234``

**app_key**
  Path to a file containing the Secret Key Zuul will use to create tokens for
  the API interactions. In Github this is known as "Private key" and must be
  collected when generated.
  ``app_key=/etc/zuul/github.key``

**api_token**
  API token for accessing GitHub if Zuul is configured with Webhooks.
  See `Creating an access token for command-line use
  <https://help.github.com/articles/creating-an-access-token-for-command-line-use/>`_.

**webhook_token**
  Required token for validating the webhook event payloads.  In the
  GitHub App Configuration page, this is called "Webhook secret".
  See `Securing your webhooks
  <https://developer.github.com/webhooks/securing/>`_.

**sshkey**
  Path to SSH key to use when cloning github repositories.
  ``sshkey=/home/zuul/.ssh/id_rsa``

**server**
  Optional: Hostname of the github install (such as a GitHub Enterprise)
  If not specified, defaults to ``github.com``
  ``server=github.myenterprise.com``

**canonical_hostname**
  The canonical hostname associated with the git repos on the GitHub
  server.  Defaults to the value of **server**.  This is used to
  identify projects from this connection by name and in preparing
  repos on the filesystem for use by jobs.  Note that Zuul will still
  only communicate with the GitHub server identified by **server**;
  this option is useful if users customarily use a different hostname
  to clone or pull git repos so that when Zuul places them in the
  job's working directory, they appear under this directory name.
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

.. _Github App: https://developer.github.com/apps/

Requirements Configuration
--------------------------

As described in :ref:`pipeline.require <pipeline-require>` and
:ref:`pipeline.reject <pipeline-reject>`, pipelines may specify that
items meet certain conditions in order to be enqueued into the
pipeline.  These conditions vary according to the source of the
project in question.  To supply requirements for changes from a GitHub
source named *my-github*, create a congfiguration such as the
following::

  pipeline:
    require:
      my-github:
        review:
          - type: approval

This indicates that changes originating from the GitHub connection
named *my-github* must have an approved code review in order to be
enqueued into the pipeline.

.. zuul:attr:: pipeline.require.<source>

   The dictionary passed to the GitHub pipeline `require` attribute
   supports the following attributes:

   .. _github-pipeline-require-review:

   .. zuul:attr:: review

      This requires that a certain kind of code review be present for
      the pull request (it could be added by the event in question).
      It takes several sub-parameters, all of which are optional and
      are combined together so that there must be a code review
      matching all specified requirements.

      .. zuul:attr:: username

         If present, a code review from this username is required.  It
         is treated as a regular expression.

      .. zuul:attr:: email

         If present, a code review with this email address is
         required.  It is treated as a regular expression.

      .. zuul:attr:: older-than

         If present, the code review must be older than this amount of
         time to match.  Provide a time interval as a number with a
         suffix of "w" (weeks), "d" (days), "h" (hours), "m"
         (minutes), "s" (seconds).  Example ``48h`` or ``2d``.

      .. zuul:attr:: newer-than

         If present, the code review must be newer than this amount of
         time to match.  Same format as "older-than".

      .. zuul:attr:: type

         If present, the code review must match this type (or types).

         .. TODO: what types are valid?

      .. zuul:attr:: permission

         If present, the author of the code review must have this
         permission (or permissions).  The available values are
         ``read``, ``write``, and ``admin``.

   .. zuul:attr:: open

      A boolean value (``true`` or ``false``) that indicates whether
      the change must be open or closed in order to be enqueued.

   .. zuul:attr:: current-patchset

      A boolean value (``true`` or ``false``) that indicates whether
      the item must be associated with the latest commit in the pull
      request in order to be enqueued.

      .. TODO: this could probably be expanded upon -- under what
         circumstances might this happen with github

   .. zuul:attr:: status

      A string value that corresponds with the status of the pull
      request.  The syntax is ``user:status:value``.

   .. zuul:attr:: label

      A string value indicating that the pull request must have the
      indicated label (or labels).


.. zuul:attr:: pipeline.reject.<source>

   The `reject` attribute is the mirror of the `require` attribute.  It
   also accepts a dictionary under the connection name.  This
   dictionary supports the following attributes:

   .. zuul:attr:: review

      This takes a list of code reviews.  If a code review matches the
      provided criteria the pull request can not be entered into the
      pipeline.  It follows the same syntax as the :ref:`review
      pipeline requirement above <github-pipeline-require-review>`.
