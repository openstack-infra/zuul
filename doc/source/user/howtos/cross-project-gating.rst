:title: Cross Project Gating

.. _cross-project-gating:

Cross Project Gating
====================

The following sections describe how to test future state of cross projects
dependencies.

Python
------

Python project's requirements are pulled from external source by default, and
the zuul-jobs tox playbook implement a special task to ensure the job required
projects are installed from the zuul src_root so that the gate effectively test
in flight project's state.

Packaging
---------

Similarly, packaging project, where tests are performed using the final binary
artifacts, would need to inject a local repository to ensure the test is using
the change as prepared by Zuul.
