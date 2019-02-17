:title: Tenant Configuration

.. _tenant-config:

Tenant Configuration
====================

After ``zuul.conf`` is configured, Zuul component servers will be able
to start, but a tenant configuration is required in order for Zuul to
perform any actions.  The tenant configuration file specifies upon
which projects Zuul should operate.  These repositories are grouped
into tenants.  The configuration of each tenant is separate from the
rest (no pipelines, jobs, etc are shared between them).

A project may appear in more than one tenant; this may be useful if
you wish to use common job definitions across multiple tenants.

The tenant configuration file is specified by the
:attr:`scheduler.tenant_config` setting in ``zuul.conf``.  It is a
YAML file which, like other Zuul configuration files, is a list of
configuration objects, though only one type of object is supported:
``tenant``.

Alternatively the :attr:`scheduler.tenant_config_script`
can be the path to an executable that will be executed and its stdout
used as the tenant configuration. The executable must return a valid
tenant YAML formatted output.

Tenant
------

A tenant is a collection of projects which share a Zuul
configuration. Some examples of tenant definitions are:

.. code-block:: yaml

   - tenant:
       name: my-tenant
       max-nodes-per-job: 5
       exclude-unprotected-branches: false
       source:
         gerrit:
           config-projects:
             - common-config
             - shared-jobs:
                 include: job
           untrusted-projects:
             - zuul-jobs:
                 shadow: common-config
             - project1
             - project2:
                 exclude-unprotected-branches: true

.. code-block:: yaml

   - tenant:
       name: my-tenant
       source:
         gerrit:
           config-projects:
             - common-config
           untrusted-projects:
             - exclude:
                 - job
                 - semaphore
                 - project
                 - project-template
                 - nodeset
                 - secret
               projects:
                 - project1
                 - project2:
                     exclude-unprotected-branches: true

.. attr:: tenant

   The following attributes are supported:

   .. attr:: name
      :required:

      The name of the tenant.  This may appear in URLs, paths, and
      monitoring fields, and so should be restricted to URL friendly
      characters (ASCII letters, numbers, hyphen and underscore) and
      you should avoid changing it unless necessary.

   .. attr:: source
      :required:

      A dictionary of sources to consult for projects.  A tenant may
      contain projects from multiple sources; each of those sources
      must be listed here, along with the projects it supports.  The
      name of a :ref:`connection<connections>` is used as the
      dictionary key (e.g. ``gerrit`` in the example above), and the
      value is a further dictionary containing the keys below.

   The next two attributes, **config-projects** and
   **untrusted-projects** provide the bulk of the information for
   tenant configuration.  They list all of the projects upon which
   Zuul will act.

   The order of the projects listed in a tenant is important.  A job
   which is defined in one project may not be redefined in another
   project; therefore, once a job appears in one project, a project
   listed later will be unable to define a job with that name.
   Further, some aspects of project configuration (such as the merge
   mode) may only be set on the first appearance of a project
   definition.

   Zuul loads the configuration from all **config-projects** in the
   order listed, followed by all **untrusted-projects** in order.

   .. attr:: config-projects

      A list of projects to be treated as :term:`config projects
      <config-project>` in this tenant.  The jobs in a config project
      are trusted, which means they run with extra privileges, do not
      have their configuration dynamically loaded for proposed
      changes, and Zuul config files are only searched for in the
      ``master`` branch.

      The items in the list follow the same format described in
      **untrusted-projects**.

   .. attr:: untrusted-projects

      A list of projects to be treated as untrusted in this tenant.
      An :term:`untrusted-project` is the typical project operated on
      by Zuul.  Their jobs run in a more restrictive environment, they
      may not define pipelines, their configuration dynamically
      changes in response to proposed changes, and Zuul will read
      configuration files in all of their branches.

      .. attr:: <project>

         The items in the list may either be simple string values of
         the project names, or a dictionary with the project name as
         key and the following values:

         .. attr:: include

            Normally Zuul will load all of the :ref:`configuration-items`
            appropriate for the type of project (config or untrusted)
            in question.  However, if you only want to load some
            items, the **include** attribute can be used to specify
            that *only* the specified items should be loaded.
            Supplied as a string, or a list of strings.

            The following **configuration items** are recognized:

            * pipeline
            * job
            * semaphore
            * project
            * project-template
            * nodeset
            * secret

         .. attr:: exclude

            A list of **configuration items** that should not be loaded.

         .. attr:: shadow

            A list of projects which this project is permitted to
            shadow.  Normally, only one project in Zuul may contain
            definitions for a given job.  If a project earlier in the
            configuration defines a job which a later project
            redefines, the later definition is considered an error and
            is not permitted.  The **shadow** attribute of a project
            indicates that job definitions in this project which
            conflict with the named projects should be ignored, and
            those in the named project should be used instead.  The
            named projects must still appear earlier in the
            configuration.  In the example above, if a job definition
            appears in both the ``common-config`` and ``zuul-jobs``
            projects, the definition in ``common-config`` will be
            used.

         .. attr:: exclude-unprotected-branches

            Define if unprotected github branches should be
            processed. Defaults to the tenant wide setting of
            exclude-unprotected-branches.

      .. attr:: <project-group>

         The items in the list are dictionaries with the following
         attributes. A **configuration items** definition is applied
         to the list of projects.

         .. attr:: include

            A list of **configuration items** that should be loaded.

         .. attr:: exclude

            A list of **configuration items** that should not be loaded.

         .. attr:: projects

            A list of **project** items.

   .. attr:: max-nodes-per-job
      :default: 5

      The maximum number of nodes a job can request.  A value of
      '-1' value removes the limit.

   .. attr:: max-job-timeout
      :default: 10800

      The maximum timeout for jobs. A value of '-1' value removes the limit.

   .. attr:: exclude-unprotected-branches
      :default: false

      When using a branch and pull model on a shared GitHub repository
      there are usually one or more protected branches which are gated
      and a dynamic number of personal/feature branches which are the
      source for the pull requests. These branches can potentially
      include broken Zuul config and therefore break the global tenant
      wide configuration. In order to deal with this Zuul's operations
      can be limited to the protected branches which are gated. This
      is a tenant wide setting and can be overridden per project.
      This currently only affects GitHub projects.

   .. attr:: default-parent
      :default: base

      If a job is defined without an explicit :attr:`job.parent`
      attribute, this job will be configured as the job's parent.
      This allows an administrator to configure a default base job to
      implement local policies such as node setup and artifact
      publishing.

   .. attr:: default-ansible-version

      Default ansible version to use for jobs that doesn't specify a version.
      See :attr:`job.ansible-version` for details.

   .. attr:: allowed-triggers
      :default: all connections

      The list of connections a tenant can trigger from. When set, this setting
      can be used to restrict what connections a tenant can use as trigger.
      Without this setting, the tenant can use any connection as a trigger.

   .. attr:: allowed-reporters
      :default: all connections

      The list of connections a tenant can report to. When set, this setting
      can be used to restrict what connections a tenant can use as reporter.
      Without this setting, the tenant can report to any connection.

   .. attr:: allowed-labels
      :default: []

      The list of labels regexp a tenant can use in job's nodeset. When set,
      this setting can be used to restrict what labels a tenant can use.
      Without this setting, the tenant can use any labels.
