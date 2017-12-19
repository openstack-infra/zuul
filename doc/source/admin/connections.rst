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
   drivers/smtp
   drivers/sql
   drivers/timer
   drivers/zuul
