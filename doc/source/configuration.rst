:title: Configuration

.. _config:

Configuration
=============

Zuul uses a very flexible configuration system.  Some initial
configuration must be supplied by the system administrator.  From that
beginning, Zuul builds its configuration by dynamically evaluating the
contents of every git repository indicated by the configuration.

Zuul configuration is focused primarily around the concept of a
*Pipeline*.  Through a pipeline, a Zuul user expresses a connection
between events, projects, jobs, and reports.  The general flow of
operations is as follows:

A *Connection* to a remote system generates an event; if it matches a
*Trigger* on a *Pipeline*, then an *Item* is enqueued into the
*Pipeline*.  An *Item* is some kind of git reference, such as a branch
tip, a proposed change, or a pull request, and is associated with a
*Project*.  Zuul launches the *Jobs* specified for that *Project* in
that *Pipeline*, and when they complete, Zuul reports the results as
specified by the pipeline's *Reporter*.

TODO: flow diagram

The following sections describe how to configure Zuul.
:ref:`admin-config` covers areas of interest primarily to system
administrators.  :ref:`project-config` covers the portion of Zuul
configuration of interest to most users -- that which is included
directly in the git repositories operated on by Zuul.

.. toctree::
   :maxdepth: 2

   admin-config
   project-config
