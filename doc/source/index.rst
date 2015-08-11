Zuul - A Project Gating System
==============================

Zuul is a program that is used to gate the source code repository of a
project so that changes are only merged if they pass tests.

The main component of Zuul is the scheduler.  It receives events
related to proposed changes, triggers tests based on those events, and
reports back.

Contents:

.. toctree::
   :maxdepth: 2

   gating
   connections
   triggers
   reporters
   zuul
   merger
   cloner
   launchers
   statsd
   client

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

