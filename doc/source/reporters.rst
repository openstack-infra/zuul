:title: Reporters

Reporters
=========

Zuul can communicate results and progress back to configurable
protocols. For example, after succeeding in a build a pipeline can be
configured to post a positive review back to gerrit.

There are three stages when a report can be handled. That is on:
Start, Success or Failure. Each stage can have multiple reports.
For example, you can set verified on gerrit and send an email.

Gerrit
------

Zuul works with standard versions of Gerrit by invoking the
``gerrit`` command over an SSH connection.  It reports back to
Gerrit using SSH.

The dictionary passed to the gerrit reporter is used for ``gerrit
review`` arguments, with the boolean value of ``true`` simply
indicating that the argument should be present without following it
with a value. For example, ``verified: 1`` becomes ``gerrit review
--verified 1`` and ``submit: true`` becomes ``gerrit review
--submit``.

Gerrit Configuration
~~~~~~~~~~~~~~~~~~~~

The configuration for posting back to gerrit is shared with the gerrit
trigger in zuul.conf. Please consult the gerrit trigger documentation.
