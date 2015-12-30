Release Notes
=============

Zuul uses `reno`_ for release note management. When adding a noteworthy
feature, fixing a noteworthy bug or introducing a behavior change that a
user or operator should know about, it is a good idea to add a release note
to the same patch.

Installing reno
---------------

reno has a command, ``reno``, that is expected to be run by developers
to create a new release note. The simplest thing to do is to install it locally
with pip:

.. code-block:: bash

  pip install --user reno

Adding a new release note
-------------------------

Adding a new release note is easy:

.. code-block:: bash

  reno new releasenote-slug

Where ``releasenote-slug`` is a short identifier for the release note.
reno will then create a file in ``releasenotes/notes`` that contains an
initial template with the available sections.

The file it creates is a yaml file. All of the sections except for ``prelude``
contain lists, which will be combined with the lists from similar sections in
other note files to create a bulleted list that will then be processed by
Sphinx.

The ``prelude`` section is a single block of text that will also be
combined with any other prelude sections into a single chunk.

.. _reno: https://docs.openstack.org/reno/latest/
