:title: Tenant Configuration

.. _tenant-config:

Tenant Configuration
====================

After *zuul.conf* is configured, Zuul component servers will be able
to start, but a tenant configuration is required in order for Zuul to
perform any actions.  The tenant configuration file specifies upon
which projects Zuul should operate.  These repositories are
grouped into tenants.  The configuration of each tenant is separate
from the rest (no pipelines, jobs, etc are shared between them).

A project may appear in more than one tenant; this may be useful if
you wish to use common job definitions across multiple tenants.

The tenant configuration file is specified by the *tenant_config*
setting in the *scheduler* section of *zuul.yaml*.  It is a YAML file
which, like other Zuul configuration files, is a list of configuration
objects, though only one type of object is supported, *tenant*.

Tenant
------

A tenant is a collection of projects which share a Zuul
configuration.  An example tenant definition is::

  - tenant:
      name: my-tenant
      source:
        gerrit:
          config-projects:
            - common-config
            - shared-jobs:
                include: jobs
          untrusted-projects:
            - project1
            - project2

The following attributes are supported:

**name** (required)
  The name of the tenant.  This may appear in URLs, paths, and
  monitoring fields, and so should be restricted to URL friendly
  characters (ASCII letters, numbers, hyphen and underscore) and you
  should avoid changing it unless necessary.

**source** (required)
  A dictionary of sources to consult for projects.  A tenant may
  contain projects from multiple sources; each of those sources must
  be listed here, along with the projects it supports.  The name of a
  :ref:`connection<connections>` is used as the dictionary key
  (e.g. `gerrit` in the example above), and the value is a further
  dictionary containing the keys below.

  **config-projects**
    A list of projects to be treated as config projects in this
    tenant.  The jobs in a config project are trusted, which means
    they run with extra privileges, do not have their configuration
    dynamically loaded for proposed changes, and zuul.yaml files are
    only searched for in the master branch.

  **untrusted-projects**
    A list of projects to be treated as untrusted in this tenant.  An
    untrusted project is the typical project operated on by Zuul.
    Their jobs run in a more restrictive environment, they may not
    define pipelines, their configuration dynamically changes in
    response to proposed changes, Zuul will read configuration files
    in all of their branches.

  Each of the projects listed may be either a simple string value, or
  it may be a dictionary with the following keys:

    **include**
    Normally Zuul will load all of the configuration classes
    appropriate for the type of project (config or untrusted) in
    question.  However, if you only want to load some items, the
    *include* attribute can be used to specify that *only* the
    specified classes should be loaded.  Supplied as a string, or a
    list of strings.

    **exclude**
    A list of configuration classes that should not be loaded.

  The order of the projects listed in a tenant is important.  A job
  which is defined in one project may not be redefined in another
  project; therefore, once a job appears in one project, a project
  listed later will be unable to define a job with that name.
  Further, some aspects of project configuration (such as the merge
  mode) may only be set on the first appearance of a project
  definition.

  Zuul loads the configuration from all *config-projects* in the order
  listed, followed by all *trusted-projects* in order.
