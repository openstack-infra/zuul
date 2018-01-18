:title: Zuul Client

Zuul Client
===========

Zuul includes a simple command line client that may be used by
administrators to affect Zuul's behavior while running.  It must be
run on a host that has access to the Gearman server (e.g., locally on
the Zuul host).

Configuration
-------------

The client uses the same zuul.conf file as the server, and will look
for it in the same locations if not specified on the command line.

Usage
-----
The general options that apply to all subcommands are:

.. program-output:: zuul --help

The following subcommands are supported:

Autohold
^^^^^^^^
.. program-output:: zuul autohold --help

Example::

  zuul autohold --tenant openstack --project example_project --job example_job --reason "reason text" --count 1

Enqueue
^^^^^^^
.. program-output:: zuul enqueue --help

Example::

  zuul enqueue --tenant openstack --trigger gerrit --pipeline check --project example_project --change 12345,1

Note that the format of change id is <number>,<patchset>.

Enqueue-ref
^^^^^^^^^^^

.. program-output:: zuul enqueue-ref --help

This command is provided to manually simulate a trigger from an
external source.  It can be useful for testing or replaying a trigger
that is difficult or impossible to recreate at the source.  The
arguments to ``enqueue-ref`` will vary depending on the source and
type of trigger.  Some familiarity with the arguments emitted by
``gerrit`` `update hooks
<https://gerrit-review.googlesource.com/admin/projects/plugins/hooks>`__
such as ``patchset-created`` and ``ref-updated`` is recommended.  Some
examples of common operations are provided below.

Manual enqueue examples
***********************

It is common to have a ``release`` pipeline that listens for new tags
coming from ``gerrit`` and performs a range of code packaging jobs.
If there is an unexpected issue in the release jobs, the same tag can
not be recreated in ``gerrit`` and the user must either tag a new
release or request a manual re-triggering of the jobs.  To re-trigger
the jobs, pass the failed tag as the ``ref`` argument and set
``newrev`` to the change associated with the tag in the project
repository (i.e. what you see from ``git show X.Y.Z``)::

  zuul enqueue-ref --tenant openstack --trigger gerrit --pipeline release --project openstack/example_project --ref refs/tags/X.Y.Z --newrev abc123...

The command can also be used asynchronosly trigger a job in a
``periodic`` pipeline that would usually be run at a specific time by
the ``timer`` driver.  For example, the following command would
trigger the ``periodic`` jobs against the current ``master`` branch
top-of-tree for a project::

  zuul enqueue-ref --tenant openstack --trigger timer --pipeline periodic --project openstack/example_project --ref refs/heads/master

Another common pipeline is a ``post`` queue listening for ``gerrit``
merge results.  Triggering here is slightly more complicated as you
wish to recreate the full ``ref-updated`` event from ``gerrit``.  For
a new commit on ``master``, the gerrit ``ref-updated`` trigger
expresses "reset ``refs/heads/master`` for the project from ``oldrev``
to ``newrev``" (``newrev`` being the committed change).  Thus to
replay the event, you could ``git log`` in the project and take the
current ``HEAD`` and the prior change, then enqueue the event::

  NEW_REF=$(git rev-parse HEAD)
  OLD_REF=$(git rev-parse HEAD~1)

  zuul enqueue-ref --tenant openstack --trigger gerrit --pipeline post --project openstack/example_project --ref refs/heads/master --newrev $NEW_REF --oldrev $OLD_REF

Note that zero values for ``oldrev`` and ``newrev`` can indicate
branch creation and deletion; the source code is the best reference
for these more advanced operations.


Promote
^^^^^^^
.. program-output:: zuul promote --help

Example::

  zuul promote --tenant openstack --pipeline check --changes 12345,1 13336,3

Note that the format of changes id is <number>,<patchset>.

Show
^^^^
.. program-output:: zuul show --help

Example::

  zuul show running-jobs
