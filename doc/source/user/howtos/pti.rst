:title: Project Testing Interface

.. _pti:

Project Testing Interface
=========================

The following sections describe an example PTI (Project Testing Interface)
implementation. The goal is to setup a consistent interface for driving tests
and other necessary tasks to succesfully configure :ref:`project_gating` within
your organization.


Projects layout
---------------

A proper PTI needs at least two projects:

* org-config: a :term:`config-project` curated by administrators, and
* org-jobs: a :term:`untrusted-project` to hold common jobs.

The projects that are being tested or deployed are also
:term:`untrusted-project`, and for the purpose of this example we will use a
couple of integrated projects named:

* org-server
* org-client


org-config
~~~~~~~~~~

The config project needs careful scrutiny as it defines priviledged Zuul
configurations that are shared by all your projects:

:ref:`pipeline` triggers and requirements let you define when a change is
tested and what are the conditions for merging code. Approval from core
members or special labels to indicate a change is good to go are pipelines
configuration.

The base job let you define how the test environment is validated before
the actual job is executed. The base job also defines how and where the job
artifacts are stored.

More importantly, a config-project may enforce a set of integration jobs to
be executed on behalf of the other projects. A regular (untrusted-project) can
only manage its own configuration, and as part of a PTI implementation, you
want to ensure your projects' changes undergo validation that are defined
globally by your organization.

Because the nature of those configuration settings are priviledged,
config-projects changes are only effective when merged.


org-jobs
~~~~~~~~

Jobs definition content are not priviledged Zuul settings and jobs can be
defined in a regular :term:`untrusted-project`.
As a matter of fact, it is recommended to define jobs outside of the config
project so that job updates can be tested before being merged.

In this example, we are using a dedicated org-jobs project.


Projects content
----------------

In this example PTI, the organization requirements are a consistent code style
and an integration test to validate org-client and org-server works according
to a reference implementation.

In the org-jobs project, we define a couple of jobs:

.. code-block:: yaml

  # org-jobs/zuul.yaml
  - job:
      name: org-codestyle
      parent: run-test-command
      vars:
        test_command: $code-style-tool $org-check-argument
        # e.g.: linters --max-column 120

  - job:
      name: org-integration-test
      run: integration-tests.yaml
      required-projects:
        - org-server
        - org-client

The integration-tests.yaml playbook needs to implement an integration test
that checks both the server and client code.


In the org-config project, we define a project template:

.. code-block:: yaml

  # org-config/zuul.d/pti.yaml
  - project-template:
      name: org-pti
      queue: integrated
      check:
        jobs:
          - org-codestyle
          - org-integration-test
      gate:
        jobs:
          - org-codestyle
          - org-integration-test


Finaly, in the org-config project, we setup the PTI template on both projects:

.. code-block:: yaml

  # org-config/zuul.d/projects.yaml
  - project:
      name: org-server
      templates:
        - org-pti

  - project:
      name: org-client
      templates:
        - org-pti


Usage
-----

With the above layout, the organization projects use a consistent testing
interface.
The org-client or org-server does not need extra settings, all new
contribution shall pass the codestyle and integration-test as defined by
the organization admin.


Project tests
~~~~~~~~~~~~~

Projects may add extra jobs on top of the PTI.
For example, the org-client project can add a user interface test:

.. code-block:: yaml

  # org-client/.zuul.yaml
  - job:
      name: org-client-ui-validation

  - project:
      check:
        jobs:
          - org-client-ui-validation
      gate:
        jobs:
          - org-client-ui-validation

In this example, new org-client change will run the PTI's jobs as well as the
org-client-ui-validation job.


Updating PTI test
~~~~~~~~~~~~~~~~~

Once the PTI is in place, if a project needs adjustment,
it can proceed as follow:

First a change on org-jobs is proposed to modify a job. For example, update a
codestyle check using such commit:

.. code-block:: text

  # org-jobs/change-url

  Update codestyle to enforce CamelCase.

Then, without merging this proposal, it can be tested accross the projects using
such commit:

.. code-block:: text

  # org-client/change-url

  Validate new codestyle.
  Depends-On: org-jobs/change-url

Lastly the org-jobs may be enriched with:

.. code-block:: text

  # org-jobs/change-url

  Update codestyle to enforce CamelCase.
  Needed-By: org-client/change-url


.. note:: Extra care is required when updating PTI jobs as they affects all
          the projects. Ideally, the org-jobs project would use a org-jobs-check
          to run PTI jobs change on every projects.


Cross project gating
--------------------

The org-pti template is using the "integrated" queue to ensure projects change
are gated by the zuul scheduler. Though, the jobs need extra care to properly
test projects as they are prepared by Zuul. For example, the
org-integration-test playbook need to ensure the client and server are installed
from the zuul src_root.

This is called sibbling installation, and it is critical piece to ensure cross
project gating. Check out the recommended practices :ref:`cross-project-gating`.
