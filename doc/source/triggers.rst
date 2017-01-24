:title: Triggers

Triggers
========

The process of merging a change starts with proposing a change to be
merged. Zuul supports Gerrit and GitHub as triggering systems.
Zuul's design is modular, so alternate triggering and reporting
systems can be supported.

Gerrit
------

Zuul works with standard versions of Gerrit by invoking the ``gerrit
stream-events`` command over an SSH connection.  It also reports back
to Gerrit using SSH.

If using Gerrit 2.7 or later, make sure the user is a member of a group
that is granted the ``Stream Events`` permission, otherwise it will not
be able to invoke the ``gerrit stream-events`` command over SSH.

A connection name with the gerrit driver can take multiple events with
the following options.

  **event**
  The event name from gerrit.  Examples: ``patchset-created``,
  ``comment-added``, ``ref-updated``.  This field is treated as a
  regular expression.

  **branch**
  The branch associated with the event.  Example: ``master``.  This
  field is treated as a regular expression, and multiple branches may
  be listed.

  **ref**
  On ref-updated events, the branch parameter is not used, instead the
  ref is provided.  Currently Gerrit has the somewhat idiosyncratic
  behavior of specifying bare refs for branch names (e.g., ``master``),
  but full ref names for other kinds of refs (e.g., ``refs/tags/foo``).
  Zuul matches what you put here exactly against what Gerrit
  provides.  This field is treated as a regular expression, and
  multiple refs may be listed.

  **ignore-deletes**
  When a branch is deleted, a ref-updated event is emitted with a newrev
  of all zeros specified. The ``ignore-deletes`` field is a boolean value
  that describes whether or not these newrevs trigger ref-updated events.
  The default is True, which will not trigger ref-updated events.

  **approval**
  This is only used for ``comment-added`` events.  It only matches if
  the event has a matching approval associated with it.  Example:
  ``code-review: 2`` matches a ``+2`` vote on the code review category.
  Multiple approvals may be listed.

  **email**
  This is used for any event.  It takes a regex applied on the performer
  email, i.e. Gerrit account email address.  If you want to specify
  several email filters, you must use a YAML list.  Make sure to use non
  greedy matchers and to escapes dots!
  Example: ``email: ^.*?@example\.org$``.

  **email_filter** (deprecated)
  A deprecated alternate spelling of *email*.  Only one of *email* or
  *email_filter* should be used.

  **username**
  This is used for any event.  It takes a regex applied on the performer
  username, i.e. Gerrit account name.  If you want to specify several
  username filters, you must use a YAML list.  Make sure to use non greedy
  matchers and to escapes dots!
  Example: ``username: ^jenkins$``.

  **username_filter** (deprecated)
  A deprecated alternate spelling of *username*.  Only one of *username* or
  *username_filter* should be used.

  **comment**
  This is only used for ``comment-added`` events.  It accepts a list of
  regexes that are searched for in the comment string. If any of these
  regexes matches a portion of the comment string the trigger is
  matched. ``comment: retrigger`` will match when comments
  containing 'retrigger' somewhere in the comment text are added to a
  change.

  **comment_filter** (deprecated)
  A deprecated alternate spelling of *comment*.  Only one of *comment* or
  *comment_filter* should be used.

  *require-approval*
  This may be used for any event.  It requires that a certain kind
  of approval be present for the current patchset of the change (the
  approval could be added by the event in question).  It follows the
  same syntax as the :ref:`"approval" pipeline requirement
  <pipeline-require-approval>`. For each specified criteria there must
  exist a matching approval.

  *reject-approval*
  This takes a list of approvals in the same format as
  *require-approval* but will fail to enter the pipeline if there is
  a matching approval.

GitHub
------

Github webhook events can be configured as triggers.

A connection name with the github driver can take multiple events with the
following options.

  **event**
  The event from github. Supported events are ``pull_request``,
  ``pull_request_review``,  and ``push``.

  A ``pull_request`` event will
  have associated action(s) to trigger from. The supported actions are:

    *opened* - pull request opened

    *changed* - pull request synchronized

    *closed* - pull request closed

    *reopened* - pull request reopened

    *comment* - comment added on pull request

    *labeled* - label added on pull request

    *unlabeled* - label removed from pull request

    *review* - review added on pull request

    *push* - head reference updated (pushed to branch)

    *status* - status set on commit

  A ``pull_request_review`` event will
  have associated action(s) to trigger from. The supported actions are:

    *submitted* - pull request review added

    *dismissed* - pull request review removed

  **branch**
  The branch associated with the event. Example: ``master``.  This
  field is treated as a regular expression, and multiple branches may
  be listed. Used for ``pull_request`` and ``pull_request_review`` events.

  **comment**
  This is only used for ``pull_request`` ``comment`` actions.  It accepts a
  list of regexes that are searched for in the comment string. If any of these
  regexes matches a portion of the comment string the trigger is matched.
  ``comment: retrigger`` will match when comments containing 'retrigger'
  somewhere in the comment text are added to a pull request.

  **label**
  This is only used for ``labeled`` and ``unlabeled`` ``pull_request`` actions.
  It accepts a list of strings each of which matches the label name in the
  event literally.  ``label: recheck`` will match a ``labeled`` action when
  pull request is labeled with a ``recheck`` label. ``label: 'do not test'``
  will match a ``unlabeled`` action when a label with name ``do not test`` is
  removed from the pull request.

  **state**
  This is only used for ``pull_request_review`` events.  It accepts a list of
  strings each of which is matched to the review state, which can be one of
  ``approved``, ``comment``, or ``request_changes``.

  **status**
  This is only used for ``status`` actions. It accepts a list of strings each of
  which matches the user setting the status, the status context, and the status
  itself in the format of ``user:context:status``.  For example,
  ``zuul_github_ci_bot:check_pipeline:success``.

  **ref**
  This is only used for ``push`` events. This field is treated as a regular
  expression and multiple refs may be listed. Github always sends full ref
  name, eg. ``refs/tags/bar`` and this string is matched against the regexp.

GitHub Configuration
~~~~~~~~~~~~~~~~~~~~

Configure GitHub `webhook events
<https://developer.github.com/webhooks/creating/>`_.

Set *Payload URL* to
``http://<zuul-hostname>/connection/<connection-name>/payload``.

Set *Content Type* to ``application/json``.

Select *Events* you are interested in. See above for the supported events.

Timer
-----

A simple timer trigger is available as well.  It supports triggering
jobs in a pipeline based on cron-style time instructions.

Timers don't require a special connection or driver. Instead they can
be used by listing **timer** as the trigger.

This trigger will run based on a cron-style time specification.
It will enqueue an event into its pipeline for every project
defined in the configuration.  Any job associated with the
pipeline will run in response to that event.

  **time**
  The time specification in cron syntax.  Only the 5 part syntax is
  supported, not the symbolic names.  Example: ``0 0 * * *`` runs
  at midnight.

Zuul
----

The Zuul trigger generates events based on internal actions in Zuul.
Multiple events may be listed.

Zuul events don't require a special connection or driver. Instead they
can be used by listing **zuul** as the trigger.

  **event**
  The event name.  Currently supported:

    *project-change-merged* when Zuul merges a change to a project,
    it generates this event for every open change in the project.

    *parent-change-enqueued* when Zuul enqueues a change into any
    pipeline, it generates this event for every child of that
    change.

  **pipeline**
  Only available for ``parent-change-enqueued`` events.  This is the
  name of the pipeline in which the parent change was enqueued.

  *require-approval*
  This may be used for any event.  It requires that a certain kind
  of approval be present for the current patchset of the change (the
  approval could be added by the event in question).  It follows the
  same syntax as the :ref:`"approval" pipeline requirement
  <pipeline-require-approval>`. For each specified criteria there must
  exist a matching approval.

  *reject-approval*
  This takes a list of approvals in the same format as
  *require-approval* but will fail to enter the pipeline if there is
  a matching approval.
