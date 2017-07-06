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

Enqueue
^^^^^^^
.. program-output:: zuul enqueue --help

Example::

  zuul enqueue --tenant openstack --trigger gerrit --pipeline check --project example_project --change 12345,1

Note that the format of change id is <number>,<patchset>.

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
