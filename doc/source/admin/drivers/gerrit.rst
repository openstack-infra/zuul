:title: Gerrit Driver

Gerrit
======

`Gerrit`_ is a code review system.  The Gerrit driver supports
sources, triggers, and reporters.

.. _Gerrit: https://www.gerritcodereview.com/

Zuul will need access to a Gerrit user.

Create an SSH keypair for Zuul to use if there isn't one already, and
create a Gerrit user with that key::

  cat ~/id_rsa.pub | ssh -p29418 review.example.com gerrit create-account --ssh-key - --full-name Zuul zuul

Give that user whatever permissions will be needed on the projects you
want Zuul to report on.  For instance, you may want to grant
``Verified +/-1`` and ``Submit`` to the user.  Additional categories
or values may be added to Gerrit.  Zuul is very flexible and can take
advantage of those.

Connection Configuration
------------------------

The supported options in zuul.conf connections are:

**driver=gerrit**

**server**
  FQDN of Gerrit server.
  ``server=review.example.com``

**canonical_hostname**
  The canonical hostname associated with the git repos on the Gerrit
  server.  Defaults to the value of **server**.  This is used to
  identify projects from this connection by name and in preparing
  repos on the filesystem for use by jobs.  Note that Zuul will still
  only communicate with the Gerrit server identified by **server**;
  this option is useful if users customarily use a different hostname
  to clone or pull git repos so that when Zuul places them in the
  job's working directory, they appear under this directory name.
  ``canonical_hostname=git.example.com``

**port**
  Optional: Gerrit server port.
  ``port=29418``

**baseurl**
  Optional: path to Gerrit web interface. Defaults to ``https://<value
  of server>/``. ``baseurl=https://review.example.com/review_site/``

**user**
  User name to use when logging into above server via ssh.
  ``user=zuul``

**sshkey**
  Path to SSH key to use when logging into above server.
  ``sshkey=/home/zuul/.ssh/id_rsa``

**keepalive**
  Optional: Keepalive timeout, 0 means no keepalive.
  ``keepalive=60``

Trigger Configuration
---------------------

Zuul works with standard versions of Gerrit by invoking the ``gerrit
stream-events`` command over an SSH connection.  It also reports back
to Gerrit using SSH.

If using Gerrit 2.7 or later, make sure the user is a member of a group
that is granted the ``Stream Events`` permission, otherwise it will not
be able to invoke the ``gerrit stream-events`` command over SSH.

The supported pipeline trigger options are:

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
  behavior of specifying bare refs for branch names (e.g.,
  ``master``), but full ref names for other kinds of refs (e.g.,
  ``refs/tags/foo``).  Zuul matches what you put here exactly against
  what Gerrit provides.  This field is treated as a regular
  expression, and multiple refs may be listed.

**ignore-deletes**
  When a branch is deleted, a ref-updated event is emitted with a
  newrev of all zeros specified. The ``ignore-deletes`` field is a
  boolean value that describes whether or not these newrevs trigger
  ref-updated events.  The default is True, which will not trigger
  ref-updated events.

**approval**
  This is only used for ``comment-added`` events.  It only matches if
  the event has a matching approval associated with it.  Example:
  ``Code-Review: 2`` matches a ``+2`` vote on the code review
  category.  Multiple approvals may be listed.

**email**
  This is used for any event.  It takes a regex applied on the
  performer email, i.e. Gerrit account email address.  If you want to
  specify several email filters, you must use a YAML list.  Make sure
  to use non greedy matchers and to escapes dots!  Example: ``email:
  ^.*?@example\.org$``.

**email_filter** (deprecated)
  A deprecated alternate spelling of *email*.  Only one of *email* or
  *email_filter* should be used.

**username**
  This is used for any event.  It takes a regex applied on the
  performer username, i.e. Gerrit account name.  If you want to
  specify several username filters, you must use a YAML list.  Make
  sure to use non greedy matchers and to escapes dots!  Example:
  ``username: ^jenkins$``.

**username_filter** (deprecated)
  A deprecated alternate spelling of *username*.  Only one of
  *username* or *username_filter* should be used.

**comment**
  This is only used for ``comment-added`` events.  It accepts a list
  of regexes that are searched for in the comment string. If any of
  these regexes matches a portion of the comment string the trigger is
  matched. ``comment: retrigger`` will match when comments containing
  'retrigger' somewhere in the comment text are added to a change.

**comment_filter** (deprecated)
  A deprecated alternate spelling of *comment*.  Only one of *comment*
  or *comment_filter* should be used.

**require-approval**
  This may be used for any event.  It requires that a certain kind of
  approval be present for the current patchset of the change (the
  approval could be added by the event in question).  It follows the
  same syntax as the :ref:`"approval" pipeline requirement
  <gerrit-pipeline-require-approval>`. For each specified criteria
  there must exist a matching approval.

**reject-approval**
  This takes a list of approvals in the same format as
  *require-approval* but will fail to enter the pipeline if there is a
  matching approval.

Reporter Configuration
----------------------

Zuul works with standard versions of Gerrit by invoking the
``gerrit`` command over an SSH connection.  It reports back to
Gerrit using SSH.

The dictionary passed to the Gerrit reporter is used for ``gerrit
review`` arguments, with the boolean value of ``true`` simply
indicating that the argument should be present without following it
with a value. For example, ``verified: 1`` becomes ``gerrit review
--verified 1`` and ``submit: true`` becomes ``gerrit review
--submit``.

A :ref:`connection<connections>` that uses the gerrit driver must be
supplied to the trigger.

Requirements Configuration
--------------------------

As described in :ref:`pipeline.require <pipeline-require>` and
:ref:`pipeline.reject <pipeline-reject>`, pipelines may specify that
items meet certain conditions in order to be enqueued into the
pipeline.  These conditions vary according to the source of the
project in question.  To supply requirements for changes from a Gerrit
source named *my-gerrit*, create a configuration such as the
following::

  pipeline:
    require:
      my-gerrit:
        approval:
          - Code-Review: 2

This indicates that changes originating from the Gerrit connection
named *my-gerrit* must have a Code Review vote of +2 in order to be
enqueued into the pipeline.

.. attr:: pipeline.require.<gerrit source>

   The dictionary passed to the Gerrit pipeline `require` attribute
   supports the following attributes:

   .. _gerrit-pipeline-require-approval:

   .. attr:: approval

      This requires that a certain kind of approval be present for the
      current patchset of the change (the approval could be added by
      the event in question).  It takes several sub-parameters, all of
      which are optional and are combined together so that there must
      be an approval matching all specified requirements.

      .. attr:: username

         If present, an approval from this username is required.  It is
         treated as a regular expression.

      .. attr:: email

         If present, an approval with this email address is required.  It is
         treated as a regular expression.

      .. attr:: older-than

         If present, the approval must be older than this amount of time
         to match.  Provide a time interval as a number with a suffix of
         "w" (weeks), "d" (days), "h" (hours), "m" (minutes), "s"
         (seconds).  Example ``48h`` or ``2d``.

      .. attr:: newer-than

         If present, the approval must be newer than this amount
         of time to match.  Same format as "older-than".

      Any other field is interpreted as a review category and value
      pair.  For example ``Verified: 1`` would require that the
      approval be for a +1 vote in the "Verified" column.  The value
      may either be a single value or a list: ``Verified: [1, 2]``
      would match either a +1 or +2 vote.

   .. attr:: open

      A boolean value (``true`` or ``false``) that indicates whether
      the change must be open or closed in order to be enqueued.

   .. attr:: current-patchset

      A boolean value (``true`` or ``false``) that indicates whether the
      change must be the current patchset in order to be enqueued.

   .. attr:: status

      A string value that corresponds with the status of the change
      reported by the trigger.

.. attr:: pipeline.reject.<gerrit source>

   The `reject` attribute is the mirror of the `require` attribute.  It
   also accepts a dictionary under the connection name.  This
   dictionary supports the following attributes:

   .. attr:: approval

      This takes a list of approvals. If an approval matches the
      provided criteria the change can not be entered into the
      pipeline. It follows the same syntax as the :ref:`approval
      pipeline requirement above <gerrit-pipeline-require-approval>`.

      Example to reject a change with any negative vote::

        reject:
          my-gerrit:
            approval:
              - Code-Review: [-1, -2]
