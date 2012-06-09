.. Zuul documentation master file, created by
   sphinx-quickstart on Fri Jun  8 14:44:26 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Zuul - A Project Gating System
==============================

Zuul is a program that is used to gate the source code repository of a
project so that changes are only merged if they pass tests.

The main component of Zuul is the scheduler.  It receives events
related to proposed changes (currently from Gerrit), triggers tests
based on those events (currently on Jenkins), and reports back.

Contents:

.. toctree::
   :maxdepth: 2

   gating
   triggers
   launchers
   zuul

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

