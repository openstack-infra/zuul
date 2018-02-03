:title: GitHub Driver

GitHub
======

The GitHub driver supports sources, triggers, and reporters.  It can
interact with the public GitHub service as well as site-local
installations of GitHub enterprise.

Configure GitHub
----------------

There are two options currently available. GitHub's project owner can either
manually setup web-hook or install a GitHub Application. In the first case,
the project's owner needs to know the zuul endpoint and the webhook secrets.


Web-Hook
........

To configure a project's `webhook events
<https://developer.github.com/webhooks/creating/>`_:

* Set *Payload URL* to
  ``http://<zuul-hostname>/connection/<connection-name>/payload``.

* Set *Content Type* to ``application/json``.

Select *Events* you are interested in. See below for the supported events.

You will also need to have a GitHub user created for your zuul:

* Zuul public key needs to be added to the GitHub account

* A api_token needs to be created too, see this `article
  <https://help.github.com/articles/creating-an-access-token-for-command-line-use/>`_

Then in the zuul.conf, set webhook_token and api_token.

Application
...........

To create a `GitHub application
<https://developer.github.com/apps/building-integrations/setting-up-and-registering-github-apps/registering-github-apps/>`_:

* Go to your organization settings page to create the application, e.g.:
  https://github.com/organizations/my-org/settings/apps/new

* Set GitHub App name to "my-org-zuul"

* Set Setup URL to your setup documentation, when user install the application
  they are redirected to this url

* Set Webhook URL to
  ``http://<zuul-hostname>/connection/<connection-name>/payload``.

* Create a Webhook secret

* Set permissions:

  * Commit statuses: Read & Write

  * Issues: Read & Write

  * Pull requests: Read & Write

  * Repository contents: Read & Write (write to let zuul merge change)

* Set events subscription:

  * Label

  * Status

  * Issue comment

  * Issues

  * Pull request

  * Pull request review

  * Pull request review comment

  * Commit comment

  * Create

  * Push

  * Release

* Set Where can this GitHub App be installed to "Any account"

* Create the App

* Generate a Private key in the app settings page

Then in the zuul.conf, set webhook_token, app_id and app_key.
After restarting zuul-scheduler, verify in the 'Advanced' tab that the
Ping payload works (green tick and 200 response)

Users can now install the application using its public page, e.g.:
https://github.com/apps/my-org-zuul


Connection Configuration
------------------------

There are two forms of operation. Either the Zuul installation can be
configured as a `Github App`_ or it can be configured as a Webhook.

If the `Github App`_ approach is taken, the config settings ``app_id`` and
``app_key`` are required. If the Webhook approach is taken, the ``api_token``
setting is required.

The supported options in ``zuul.conf`` connections are:

.. attr:: <github connection>

   .. attr:: driver
      :required:

      .. value:: github

         The connection must set ``driver=github`` for GitHub connections.

   .. attr:: app_id

      App ID if you are using a *GitHub App*. Can be found under the
      **Public Link** on the right hand side labeled **ID**.

   .. attr:: app_key

      Path to a file containing the secret key Zuul will use to create
      tokens for the API interactions. In Github this is known as
      **Private key** and must be collected when generated.

   .. attr:: api_token

      API token for accessing GitHub if Zuul is configured with
      Webhooks.  See `Creating an access token for command-line use
      <https://help.github.com/articles/creating-an-access-token-for-command-line-use/>`_.

   .. attr:: webhook_token

      Required token for validating the webhook event payloads.  In
      the GitHub App Configuration page, this is called **Webhook
      secret**.  See `Securing your webhooks
      <https://developer.github.com/webhooks/securing/>`_.

   .. attr:: sshkey
      :default: ~/.ssh/id_rsa

      Path to SSH key to use when cloning github repositories.

   .. attr:: server
      :default: github.com

      Hostname of the github install (such as a GitHub Enterprise).

   .. attr:: canonical_hostname

      The canonical hostname associated with the git repos on the
      GitHub server.  Defaults to the value of :attr:`<github
      connection>.server`.  This is used to identify projects from
      this connection by name and in preparing repos on the filesystem
      for use by jobs.  Note that Zuul will still only communicate
      with the GitHub server identified by **server**; this option is
      useful if users customarily use a different hostname to clone or
      pull git repos so that when Zuul places them in the job's
      working directory, they appear under this directory name.

   .. attr:: verify_ssl
      :default: true

      Enable or disable ssl verification for GitHub Enterprise.  This
      is useful for a connection to a test installation.

Trigger Configuration
---------------------
GitHub webhook events can be configured as triggers.

A connection name with the GitHub driver can take multiple events with
the following options.

.. attr:: pipeline.trigger.<github source>

   The dictionary passed to the GitHub pipeline ``trigger`` attribute
   supports the following attributes:

   .. attr:: event
      :required:

      The event from github. Supported events are:

      .. value:: pull_request

      .. value:: pull_request_review

      .. value:: push

   .. attr:: action

      A :value:`pipeline.trigger.<github source>.event.pull_request`
      event will have associated action(s) to trigger from. The
      supported actions are:

      .. value:: opened

         Pull request opened.

      .. value:: changed

         Pull request synchronized.

      .. value:: closed

         Pull request closed.

      .. value:: reopened

         Pull request reopened.

      .. value:: comment

         Comment added to pull request.

      .. value:: labeled

         Label added to pull request.

      .. value:: unlabeled

         Label removed from pull request.

      .. value:: status

         Status set on commit.

      A :value:`pipeline.trigger.<github
      source>.event.pull_request_review` event will have associated
      action(s) to trigger from. The supported actions are:

      .. value:: submitted

         Pull request review added.

      .. value:: dismissed

         Pull request review removed.

   .. attr:: branch

      The branch associated with the event. Example: ``master``.  This
      field is treated as a regular expression, and multiple branches
      may be listed. Used for ``pull_request`` and
      ``pull_request_review`` events.

   .. attr:: comment

      This is only used for ``pull_request`` ``comment`` actions.  It
      accepts a list of regexes that are searched for in the comment
      string. If any of these regexes matches a portion of the comment
      string the trigger is matched.  ``comment: retrigger`` will
      match when comments containing 'retrigger' somewhere in the
      comment text are added to a pull request.

   .. attr:: label

      This is only used for ``labeled`` and ``unlabeled``
      ``pull_request`` actions.  It accepts a list of strings each of
      which matches the label name in the event literally.  ``label:
      recheck`` will match a ``labeled`` action when pull request is
      labeled with a ``recheck`` label. ``label: 'do not test'`` will
      match a ``unlabeled`` action when a label with name ``do not
      test`` is removed from the pull request.

   .. attr:: state

      This is only used for ``pull_request_review`` events.  It
      accepts a list of strings each of which is matched to the review
      state, which can be one of ``approved``, ``comment``, or
      ``request_changes``.

   .. attr:: status

      This is used for ``pull-request`` and ``status`` actions. It
      accepts a list of strings each of which matches the user setting
      the status, the status context, and the status itself in the
      format of ``user:context:status``.  For example,
      ``zuul_github_ci_bot:check_pipeline:success``.

   .. attr:: ref

      This is only used for ``push`` events. This field is treated as
      a regular expression and multiple refs may be listed. GitHub
      always sends full ref name, eg. ``refs/tags/bar`` and this
      string is matched against the regular expression.

Reporter Configuration
----------------------
Zuul reports back to GitHub via GitHub API. Available reports include a PR
comment containing the build results, a commit status on start, success and
failure, an issue label addition/removal on the PR, and a merge of the PR
itself. Status name, description, and context is taken from the pipeline.

.. attr:: pipeline.<reporter>.<github source>

   To report to GitHub, the dictionaries passed to any of the pipeline
   :ref:`reporter<reporters>` attributes support the following
   attributes:

   .. attr:: status

      String value (``pending``, ``success``, ``failure``) that the
      reporter should set as the commit status on github.

   .. TODO support role markup in :default: so we can xref
      :attr:`web.status_url` below

   .. attr:: status-url
      :default: web.status_url or the empty string

      String value for a link url to set in the github
      status. Defaults to the zuul server status_url, or the empty
      string if that is unset.

   .. attr:: comment
      :default: true

      Boolean value that determines if the reporter should add a
      comment to the pipeline status to the github pull request. Only
      used for Pull Request based items.

   .. attr:: merge
      :default: false

      Boolean value that determines if the reporter should merge the
      pull reqeust. Only used for Pull Request based items.

   .. attr:: label

      List of strings each representing an exact label name which
      should be added to the pull request by reporter. Only used for
      Pull Request based items.

   .. attr:: unlabel

      List of strings each representing an exact label name which
      should be removed from the pull request by reporter. Only used
      for Pull Request based items.

.. _Github App: https://developer.github.com/apps/

Requirements Configuration
--------------------------

As described in :attr:`pipeline.require` and :attr:`pipeline.reject`,
pipelines may specify that items meet certain conditions in order to
be enqueued into the pipeline.  These conditions vary according to the
source of the project in question.  To supply requirements for changes
from a GitHub source named ``my-github``, create a congfiguration such
as the following::

  pipeline:
    require:
      my-github:
        review:
          - type: approval

This indicates that changes originating from the GitHub connection
named ``my-github`` must have an approved code review in order to be
enqueued into the pipeline.

.. attr:: pipeline.require.<github source>

   The dictionary passed to the GitHub pipeline `require` attribute
   supports the following attributes:

   .. attr:: review

      This requires that a certain kind of code review be present for
      the pull request (it could be added by the event in question).
      It takes several sub-parameters, all of which are optional and
      are combined together so that there must be a code review
      matching all specified requirements.

      .. attr:: username

         If present, a code review from this username is required.  It
         is treated as a regular expression.

      .. attr:: email

         If present, a code review with this email address is
         required.  It is treated as a regular expression.

      .. attr:: older-than

         If present, the code review must be older than this amount of
         time to match.  Provide a time interval as a number with a
         suffix of "w" (weeks), "d" (days), "h" (hours), "m"
         (minutes), "s" (seconds).  Example ``48h`` or ``2d``.

      .. attr:: newer-than

         If present, the code review must be newer than this amount of
         time to match.  Same format as "older-than".

      .. attr:: type

         If present, the code review must match this type (or types).

         .. TODO: what types are valid?

      .. attr:: permission

         If present, the author of the code review must have this
         permission (or permissions).  The available values are
         ``read``, ``write``, and ``admin``.

   .. attr:: open

      A boolean value (``true`` or ``false``) that indicates whether
      the change must be open or closed in order to be enqueued.

   .. attr:: current-patchset

      A boolean value (``true`` or ``false``) that indicates whether
      the item must be associated with the latest commit in the pull
      request in order to be enqueued.

      .. TODO: this could probably be expanded upon -- under what
         circumstances might this happen with github

   .. attr:: status

      A string value that corresponds with the status of the pull
      request.  The syntax is ``user:status:value``.

   .. attr:: label

      A string value indicating that the pull request must have the
      indicated label (or labels).

.. attr:: pipeline.reject.<github source>

   The `reject` attribute is the mirror of the `require` attribute.  It
   also accepts a dictionary under the connection name.  This
   dictionary supports the following attributes:

   .. attr:: review

      This takes a list of code reviews.  If a code review matches the
      provided criteria the pull request can not be entered into the
      pipeline.  It follows the same syntax as
      :attr:`pipeline.require.<github source>.review`
