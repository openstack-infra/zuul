:title: Job Content

Job Content
===========

Zuul jobs are implemneted as Ansible playbooks.  Zuul prepares the
repositories used for a job, installs any required Ansible roles, and
then executes the job's playbooks.  Any setup or artifact collection
required is the responsibility of the job itself.  While this flexible
arrangement allows for almost any kind of job to be run by Zuul,
batteries are included.  Zuul has a standard library of jobs upon
which to build.

Working Directory
-----------------

Before starting each job, the Zuul executor creates a directory to
hold all of the content related to the job.  This includes some
directories which are used by Zuul to configure and run Ansible and
may not be accessible, as well as a directory tree, under ``work/``,
that is readable and writable by the job.  The hierarchy is:

**work/**
  The working directory of the job.

**work/src/**
  Contains the prepared git repositories for the job.

**work/logs/**
  Where the Ansible log for the job is written; your job
  may place other logs here as well.

Git Repositories
----------------

The git repositories in ``work/src`` contain the repositories for all
of the projects specified in the ``required-projects`` section of the
job, plus the project associated with the queue item if it isn't
already in that list.  In the case of a proposed change, that change
and all of the changes ahead of it in the pipeline queue will already
be merged into their respective repositories and target branches.  The
change's project will have the change's branch checked out, as will
all of the other projects, if that branch exists (otherwise, a
fallback or default branch will be used).  If your job needs to
operate on multiple branches, simply checkout the appropriate branches
of these git repos to ensure that the job results reflect the proposed
future state that Zuul is testing, and all dependencies are present.
Do not use any git remotes; the local repositories are guaranteed to
be up to date.

The repositories will be placed on the filesystem in directories
corresponding with the canonical hostname of their source connection.
For example::

  work/src/git.example.com/project1
  work/src/github.com/project2

Is the layout that would be present for a job which included project1
from the connection associated to git.example.com and project2 from
GitHub.  This helps avoid collisions between projects with the same
name, and some language environments, such as Go, expect repositories
in this format.

Note that these git repositories are located on the executor; in order
to be useful to most kinds of jobs, they will need to be present on
the test nodes.  The ``base`` job in the standard library contains a
pre-playbook which copies the repositories to all of the job's nodes.
It is recommended to always inherit from this base job to ensure that
behavior.

.. TODO: link to base job documentation and/or document src (and logs?) directory

Variables
---------

Any variables specified in the job definition are available as Ansible
host variables.  They are added to the `vars` section of the inventory
file under the `all` hosts group, so they are available to all hosts.
Simply refer to them by the name specified in the job's `vars`
section.

Secrets
~~~~~~~

Secrets also appear as variables available to Ansible.  Unlike job
variables, these are not added to the inventory file (so that the
inventory file may be kept for debugging purposes without revealing
secrets).  But they are still available to Ansible as normal
variables.  Because secrets are groups of variables, they will appear
as a dictionary structure in templates, with the dictionary itself
being the name of the secret, and its members the individual items in
the secret.  For example, a secret defined as::

  - secret:
      name: credentials
      data:
        username: foo
        password: bar

Might be used in a template as::

 {{ credentials.username }} {{ credentials.password }}

.. TODO: xref job vars

Zuul Variables
~~~~~~~~~~~~~~

Zuul supplies not only the variables specified by the job definition
to Ansible, but also some variables from the Zuul itself.

When a pipeline is triggered an action, it enqueues items which may
vary based on the pipeline's configuration.  For example, when a new
change is created, that change may be enqueued into the pipeline,
while a tag may be enqueued into the pipeline when it is pushed.

Information about these items is available to jobs.  All of the items
enqueued in a pipeline are git references, and therefore share some
attributes in common.  But other attributes may vary based on the type
of item.

All items provide the following information as Ansible variables:

**zuul.build**
  The UUID of the build.  A build is a single execution of a job.
  When an item is enqueued into a pipeline, this usually results in
  one build of each job configured for that item's project.  However,
  items may be re-enqueued in which case another build may run.  In
  dependent pipelines, the same job may run multiple times for the
  same item as circumstances change ahead in the queue.  Each time a
  job is run, for whatever reason, it is acompanied with a new
  unique id.

**zuul.buildset**
  The build set UUID.  When Zuul runs jobs for an item, the collection
  of those jobs is known as a buildset.  If the configuration of items
  ahead in a dependent pipeline changes, Zuul creates a new buildset
  and restarts all of the jobs.

**zuul.ref**
  The git ref of the item.  This will be the full path (e.g.,
  'refs/heads/master' or 'refs/changes/...').

**zuul.pipeline**
  The name of the pipeline in which the job is being run.

**zuul.job**
  The name of the job being run.

**zuul.project**
  The item's project.  This is a data structure with the following
  fields:

**zuul.project.name**
  The name of the project, excluding hostname.  E.g., `org/project`.

**zuul.project.canonical_hostname**
  The canonical hostname where the project lives.  E.g.,
  `git.example.com`.

**zuul.project.canonical_name**
  The full canonical name of the project including hostname.  E.g.,
  `git.example.com/org/project`.

**zuul.tenant**
  The name of the current Zuul tenant.

**zuul.jobtags**
  A list of tags associated with the job.  Not to be confused with git
  tags, these are simply free-form text fields that can be used by the
  job for reporting or classification purposes.

**zuul.items**
  A data structure representing the items being tested with this
  change.

.. TODO: implement and document items


Change Items
++++++++++++

A change to the repository.  Most often, this will be a git reference
which has not yet been merged into the repository (e.g., a gerrit
change or a GitHub pull request).  The following additional variables
are available:

**zuul.branch**
  The target branch of the change (without the `refs/heads/` prefix).

**zuul.change**
  The identifier for the change.

**zuul.patchset**
  The patchset identifier for the change.  If a change is revised,
  this will have a different value.

Branch Items
++++++++++++

This represents a branch tip.  This item may have been enqueued
because the branch was updated (via a change having merged, or a
direct push).  Or it may have been enqueued by a timer for the purpose
of verifying the current condition of the branch.  The following
additional variables are available:

**zuul.branch**
  The name of the item's branch (without the `refs/heads/` prefix).

**zuul.oldrev**
  If the item was enqueued as the result of a change merging or being
  pushed to the branch, the git sha of the old revision will be
  included here.  Otherwise, this value will not be present.

**zuul.newrev**
  If the item was enqueued as the result of a change merging or being
  pushed to the branch, the git sha of the new revision will be
  included here.  Otherwise, this value will not be present.

Tag Items
+++++++++

This represents a git tag.  The item may have been enqueued because a
tag was created or deleted.  The following additional variables are
available:

**zuul.tag**
  The name of the item's tag (without the `refs/tags/` prefix).

**zuul.oldrev**
  If the item was enqueued as the result of a tag being created or
  deleted the git sha of the old revision will be included here.
  Otherwise, this value will not be present.

**zuul.newrev**
  If the item was enqueued as the result of a tag being created or
  deleted the git sha of the new revision will be included here.
  Otherwise, this value will not be present.

Ref Items
+++++++++

This represents a git reference that is neither a change, branch, or
tag.  Note that all items include a `ref` attribute which may be used
to identify the ref.  The following additional variables are
available:

**zuul.oldrev**
  If the item was enqueued as the result of a ref being created,
  deleted, or changed the git sha of the old revision will be included
  here.  Otherwise, this value will not be present.

**zuul.newrev**
  If the item was enqueued as the result of a ref being created,
  deleted, or changed the git sha of the new revision will be included
  here.  Otherwise, this value will not be present.

Working Directory
+++++++++++++++++

Additionally, some information about the working directory and the
executor running the job is available:

**zuul.executor.hostname**
  The hostname of the executor.

**zuul.executor.src_root**
  The path to the source directory.

**zuul.executor.log_root**
  The path to the logs directory.

SSH Keys
--------

Zuul starts each job with an SSH agent running and the key used to
access the job's nodes added to that agent.  Generally you won't need
to be aware of this since Ansible will use this when performing any
tasks on remote nodes.  However, under some circumstances you may want
to interact with the agent.  For example, you may wish to add a key
provided as a secret to the job in order to access a specific host, or
you may want to, in a pre-playbook, replace the key used to log into
the assigned nodes in order to further protect it from being abused by
untrusted job content.

.. TODO: describe standard lib and link to published docs for it.

.. _return_values:

Return Values
-------------

The job may return some values to Zuul to affect its behavior.  To
return a value, use the *zuul_return* Ansible module in a job
playbook.  For example::

  tasks:
    - zuul_return:
        data:
          foo: bar

Will return the dictionary "{'foo': 'bar'}" to Zuul.

.. TODO: xref to section describing formatting

Several uses of these values are planned, but the only currently
implemented use is to set the log URL for a build.  To do so, set the
**zuul.log_url** value.  For example::

  tasks:
    - zuul_return:
        data:
          zuul:
            log_url: http://logs.example.com/path/to/build/logs
