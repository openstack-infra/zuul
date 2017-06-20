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
  identify repos from this connection by name and in preparing repos
  on the filesystem for use by jobs.
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
