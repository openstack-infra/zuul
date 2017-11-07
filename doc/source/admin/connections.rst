:title: Connection Configuration

.. _connection-config:

Connection Configuration
========================

Most of Zuul's configuration is contained in the git repositories upon
which Zuul operates, however, some configuration outside of git
repositories is still required to bootstrap the system.  This includes
information on connections between Zuul and other systems, as well as
identifying the projects Zuul uses.

.. _connections:

Connections
-----------

In order to interact with external systems, Zuul must have a
*connection* to that system configured.  Zuul includes a number of
drivers, each of which implements the functionality necessary to
connect to a system.  Each connection in Zuul is associated with a
driver.

To configure a connection in Zuul, select a unique name for the
connection and add a section to ``zuul.conf`` with the form
``[connection NAME]``.  For example, a connection to a gerrit server
may appear as:

.. code-block:: ini

  [connection mygerritserver]
  driver=gerrit
  server=review.example.com

Zuul needs to use a single connection to look up information about
changes hosted by a given system.  When it looks up changes, it will
do so using the first connection it finds that matches the server name
it's looking for.  It's generally best to use only a single connection
for a given server, however, if you need more than one (for example,
to satisfy unique reporting requirements) be sure to list the primary
connection first as that is what Zuul will use to look up all changes
for that server.

.. _drivers:

Drivers
-------

Drivers may support any of the following functions:

* Sources -- hosts git repositories for projects.  Zuul can clone git
  repos for projects and fetch refs.
* Triggers -- emits events to which Zuul may respond.  Triggers are
  configured in pipelines to cause changes or other refs to be
  enqueued.
* Reporters -- outputs information when a pipeline is finished
  processing an item.

Zuul includes the following drivers:

.. toctree::
   :maxdepth: 2

   drivers/gerrit
   drivers/github
   drivers/git
   drivers/mqtt
   drivers/smtp
   drivers/sql
   drivers/timer
   drivers/zuul
