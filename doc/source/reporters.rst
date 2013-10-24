:title: Reporters

Reporters
=========

Zuul can communicate results and progress back to configurable
protocols. For example, after succeeding in a build a pipeline can be
configured to post a positive review back to Gerrit.

There are three stages when a report can be handled. That is on:
Start, Success or Failure. Each stage can have multiple reports.
For example, you can set verified on Gerrit and send an email.

Gerrit
------

Zuul works with standard versions of Gerrit by invoking the
``gerrit`` command over an SSH connection.  It reports back to
Gerrit using SSH.

The dictionary passed to the Gerrit reporter is used for ``gerrit
review`` arguments, with the boolean value of ``true`` simply
indicating that the argument should be present without following it
with a value. For example, ``verified: 1`` becomes ``gerrit review
--verified 1`` and ``submit: true`` becomes ``gerrit review
--submit``.

Gerrit Configuration
~~~~~~~~~~~~~~~~~~~~

The configuration for posting back to Gerrit is shared with the Gerrit
trigger in zuul.conf as described in :ref:`zuulconf`.

SMTP
----

A simple email reporter is also available.

SMTP Configuration
~~~~~~~~~~~~~~~~~~

zuul.conf contains the SMTP server and default to/from as describe
in :ref:`zuulconf`.

Each pipeline can overwrite the to or from address by providing
alternatives as arguments to the reporter. For example, ::

  pipelines:
    - name: post-merge
      manager: IndependentPipelineManager
      trigger:
        - event: change-merged
      success:
        smtp:
          to: you@example.com
      failure:
        smtp:
          to: you@example.com
          from: alternative@example.com
