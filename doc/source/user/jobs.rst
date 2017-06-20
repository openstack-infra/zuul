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

Note that these git repositories are located on the executor; in order
to be useful to most kinds of jobs, they will need to be present on
the test nodes.  The ``base`` job in the standard library contains a
pre-playbook which copies the repositories to all of the job's nodes.
It is recommended to always inherit from this base job to ensure that
behavior.

.. TODO: link to base job documentation and/or document src (and logs?) directory

Zuul Variables
--------------

Zuul supplies not only the variables specified by the job definition
to Ansible, but also some variables from the executor itself.  They
are:

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

