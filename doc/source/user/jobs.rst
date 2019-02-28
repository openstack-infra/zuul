:title: Job Content

Job Content
===========

Zuul jobs are implemented as Ansible playbooks.  Zuul prepares the
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

The git repositories will have a remote ``origin`` with refs pointing
to the previous change in the speculative state. This means that e.g.
a ``git diff origin/<branch>..<branch>`` will show the changes being
tested. Note that the ``origin`` URL is set to a bogus value
(``file:///dev/null``) and can not be used for updating the repository
state; the local repositories are guaranteed to be up to date.

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
the test nodes.  The ``base`` job in the standard library (see
`zuul-base-jobs documentation`_ for details) contains a
pre-playbook which copies the repositories to all of the job's nodes.
It is recommended to always inherit from this base job to ensure that
behavior.

.. _zuul-base-jobs documentation: https://zuul-ci.org/docs/zuul-base-jobs/jobs.html#job-base

.. TODO: document src (and logs?) directory

.. _user_jobs_variable_inheritance:

Variables
---------

There are several sources of variables which are available to Ansible:
variables defined in jobs, secrets, and site-wide variables.  The
order of precedence is:

#. :ref:`Site-wide variables <user_jobs_sitewide_variables>`
#. :ref:`Job extra variables <user_jobs_job_extra_variables>`
#. :ref:`Secrets <user_jobs_secrets>`
#. :ref:`Job variables <user_jobs_job_variables>`
#. :ref:`Project variables <user_jobs_project_variables>`
#. :ref:`Parent job results <user_jobs_parent_results>`

Meaning that a site-wide variable with the same name as any other will
override its value, and similarly, secrets override job variables of
the same name which override data returned from parent jobs.  Each of
the sources is described below.

.. _user_jobs_sitewide_variables:

Site-wide Variables
~~~~~~~~~~~~~~~~~~~

The Zuul administrator may define variables which will be available to
all jobs running in the system.  These are statically defined and may
not be altered by jobs.  See the :ref:`Administrator's Guide
<admin_sitewide_variables>` for information on how a site
administrator may define these variables.

.. _user_jobs_job_extra_variables:

Job Extra Variables
~~~~~~~~~~~~~~~~~~~

Any extra variables in the job definition (using the :attr:`job.extra-vars`
attribute) are available to Ansible but not added into the inventory file.

.. _user_jobs_secrets:

Secrets
~~~~~~~

:ref:`Secrets <secret>` also appear as variables available to Ansible.
Unlike job variables, these are not added to the inventory file (so
that the inventory file may be kept for debugging purposes without
revealing secrets).  But they are still available to Ansible as normal
variables.  Because secrets are groups of variables, they will appear
as a dictionary structure in templates, with the dictionary itself
being the name of the secret, and its members the individual items in
the secret.  For example, a secret defined as:

.. code-block:: yaml

  - secret:
      name: credentials
      data:
        username: foo
        password: bar

Might be used in a template as::

 {{ credentials.username }} {{ credentials.password }}

Secrets are only available to playbooks associated with the job
definition which uses the secret; they are not available to playbooks
associated with child jobs or job variants.

.. _user_jobs_job_variables:

Job Variables
~~~~~~~~~~~~~

Any variables specified in the job definition (using the
:attr:`job.vars` attribute) are available as Ansible host variables.
They are added to the ``vars`` section of the inventory file under the
``all`` hosts group, so they are available to all hosts.  Simply refer
to them by the name specified in the job's ``vars`` section.

.. _user_jobs_project_variables:

Project Variables
~~~~~~~~~~~~~~~~~

Any variables specified in the project definition (using the
:attr:`project.vars` attribute) are available to jobs as Ansible host
variables in the same way as :ref:`job variables
<user_jobs_job_variables>`.  Variables set in a ``project-template``
are merged into the project variables when the template is included by
a project.

.. code-block:: yaml

  - project-template:
      name: sample-template
      description: Description
      vars:
        var_from_template: foo
      post:
        jobs:
          - template_job
      release:
        jobs:
          - template_job

  - project:
      name: Sample project
      description: Description
      templates:
        - sample-template
      vars:
        var_for_all_jobs: value
      check:
        jobs:
          - job1
          - job2:
              vars:
                var_for_all_jobs: override

.. _user_jobs_parent_results:

Parent Job Results
~~~~~~~~~~~~~~~~~~

A job may return data to Zuul for later use by jobs which depend on
it.  For details, see :ref:`return_values`.

Zuul Variables
--------------

Zuul supplies not only the variables specified by the job definition
to Ansible, but also some variables from Zuul itself.

When a pipeline is triggered by an action, it enqueues items which may
vary based on the pipeline's configuration.  For example, when a new
change is created, that change may be enqueued into the pipeline,
while a tag may be enqueued into the pipeline when it is pushed.

Information about these items is available to jobs.  All of the items
enqueued in a pipeline are git references, and therefore share some
attributes in common.  But other attributes may vary based on the type
of item.

.. var:: zuul

   All items provide the following information as Ansible variables
   under the ``zuul`` key:

   .. var:: artifacts
      :type: list

      If the job has a :attr:`job.requires` attribute, and Zuul has
      found changes ahead of this change in the pipeline with matching
      :attr:`job.provides` attributes, then information about any
      :ref:`artifacts returned <return_artifacts>` from those jobs
      will appear here.

      This value is a list of dictionaries with the following format:

      .. var:: project

         The name of the project which supplied this artifact.

      .. var:: change

         The change number which supplied this artifact.

      .. var:: patchset

         The patchset of the change.

      .. var:: job

         The name of the job which produced the artifact.

      .. var:: name

         The name of the artifact (as supplied to :ref:`return_artifacts`).

      .. var:: url

         The URL of the artifact (as supplied to :ref:`return_artifacts`).

      .. var:: metadata

         The metadata of the artifact (as supplied to :ref:`return_artifacts`).

   .. var:: build

      The UUID of the build.  A build is a single execution of a job.
      When an item is enqueued into a pipeline, this usually results
      in one build of each job configured for that item's project.
      However, items may be re-enqueued in which case another build
      may run.  In dependent pipelines, the same job may run multiple
      times for the same item as circumstances change ahead in the
      queue.  Each time a job is run, for whatever reason, it is
      acompanied with a new unique id.

   .. var:: buildset

      The build set UUID.  When Zuul runs jobs for an item, the
      collection of those jobs is known as a buildset.  If the
      configuration of items ahead in a dependent pipeline changes,
      Zuul creates a new buildset and restarts all of the jobs.

   .. var:: child_jobs

      A list of the first level child jobs to be run after this job
      has finished successfully.

   .. var:: ref

      The git ref of the item.  This will be the full path (e.g.,
      `refs/heads/master` or `refs/changes/...`).

   .. var:: override_checkout

      If the job was configured to override the branch or tag checked
      out, this will contain the specified value.  Otherwise, this
      variable will be undefined.

   .. var:: pipeline

      The name of the pipeline in which the job is being run.

   .. var:: job

      The name of the job being run.

   .. var:: voting

      A boolean indicating whether the job is voting.

   .. var:: project

      The item's project.  This is a data structure with the following
      fields:

      .. var:: name

         The name of the project, excluding hostname.  E.g., `org/project`.

      .. var:: short_name

         The name of the project, excluding directories or
         organizations.  E.g., `project`.

      .. var:: canonical_hostname

         The canonical hostname where the project lives.  E.g.,
         `git.example.com`.

      .. var:: canonical_name

         The full canonical name of the project including hostname.
         E.g., `git.example.com/org/project`.

      .. var:: src_dir

         The path to the source code relative to the work dir.  E.g.,
         `src/git.example.com/org/project`.

   .. var:: projects
      :type: dict

      A dictionary of all projects prepared by Zuul for the item.  It
      includes, at least, the item's own project.  It also includes
      the projects of any items this item depends on, as well as the
      projects that appear in :attr:`job.required-projects`.

      This is a dictionary of dictionaries.  Each value has a key of
      the `canonical_name`, then each entry consists of:

      .. var:: name

         The name of the project, excluding hostname.  E.g., `org/project`.

      .. var:: short_name

         The name of the project, excluding directories or
         organizations.  E.g., `project`.

      .. var:: canonical_hostname

         The canonical hostname where the project lives.  E.g.,
         `git.example.com`.

      .. var:: canonical_name

         The full canonical name of the project including hostname.
         E.g., `git.example.com/org/project`.

      .. var:: src_dir

         The path to the source code, relative to the work dir.  E.g.,
         `src/git.example.com/org/project`.

      .. var:: required

         A boolean indicating whether this project appears in the
         :attr:`job.required-projects` list for this job.

      .. var:: checkout

         The branch or tag that Zuul checked out for this project.
         This may be influenced by the branch or tag associated with
         the item as well as the job configuration.

      For example, to access the source directory of a single known
      project, you might use::

        {{ zuul.projects['git.example.com/org/project'].src_dir }}

      To iterate over the project list, you might write a task
      something like::

        - name: Sample project iteration
          debug:
            msg: "Project {{ item.name }} is at {{ item.src_dir }}
          with_items: {{ zuul.projects.values() | list }}

   .. var:: tenant

      The name of the current Zuul tenant.

   .. var:: timeout

      The job timeout, in seconds.

   .. var:: post_timeout

      The post-run playbook timeout, in seconds.

   .. var:: jobtags

      A list of tags associated with the job.  Not to be confused with
      git tags, these are simply free-form text fields that can be
      used by the job for reporting or classification purposes.

   .. var:: items
      :type: list

      A list of dictionaries, each representing an item being tested
      with this change with the format:

      .. var:: project

         The item's project.  This is a data structure with the
         following fields:

         .. var:: name

            The name of the project, excluding hostname.  E.g.,
            `org/project`.

         .. var:: short_name

            The name of the project, excluding directories or
            organizations.  E.g., `project`.

         .. var:: canonical_hostname

            The canonical hostname where the project lives.  E.g.,
            `git.example.com`.

         .. var:: canonical_name

            The full canonical name of the project including hostname.
            E.g., `git.example.com/org/project`.

         .. var:: src_dir

            The path to the source code on the remote host, relative
            to the home dir of the remote user.
            E.g., `src/git.example.com/org/project`.

      .. var:: branch

         The target branch of the change (without the `refs/heads/` prefix).

      .. var:: change

         The identifier for the change.

      .. var:: change_url

         The URL to the source location of the given change.
         E.g., `https://review.example.org/#/c/123456/` or
         `https://github.com/example/example/pull/1234`.

      .. var:: patchset

         The patchset identifier for the change.  If a change is
         revised, this will have a different value.


      .. var:: resources
         :type: dict

         A job using a container build resources has access to a resources variable
         that describes the resource. Resources is a dictionary of group keys,
         each value consists of:

        .. var:: namespace

            The resource's namespace name.

        .. var:: context

            The kube config context name.

        .. var:: pod

            The name of the pod when the label defines a kubectl connection.

        Project or namespace resources might be used in a template as:

        .. code-block:: yaml

            - hosts: localhost
                tasks:
                - name: Create a k8s resource
                  k8s_raw:
                    state: present
                    context: "{{ zuul.resources['node-name'].context }}"
                    namespace: "{{ zuul.resources['node-name'].namespace }}"

        Kubectl resources might be used in a template as:

        .. code-block:: yaml

            - hosts: localhost
                tasks:
                - name: Copy src repos to the pod
                  command: >
                    oc rsync -q --progress=false
                        {{ zuul.executor.src_root }}/
                        {{ zuul.resources['node-name'].pod }}:src/
                    no_log: true


.. var:: zuul_success

   Post run playbook(s) will be passed this variable to indicate if the run
   phase of the job was successful or not. This variable is meant to be used
   with the `bool` filter.

   .. code-block:: yaml

     tasks:
       - shell: echo example
         when: zuul_success | bool


Change Items
~~~~~~~~~~~~

A change to the repository.  Most often, this will be a git reference
which has not yet been merged into the repository (e.g., a gerrit
change or a GitHub pull request).  The following additional variables
are available:

.. var:: zuul
   :hidden:

   .. var:: branch

      The target branch of the change (without the `refs/heads/` prefix).

   .. var:: change

      The identifier for the change.

   .. var:: patchset

      The patchset identifier for the change.  If a change is revised,
      this will have a different value.

   .. var:: change_url

      The URL to the source location of the given change.
      E.g., `https://review.example.org/#/c/123456/` or
      `https://github.com/example/example/pull/1234`.

   .. var:: message

      The commit or pull request message of the change base64 encoded. Use the
      `b64decode` filter in ansible when working with it.

      .. code-block:: yaml

         - hosts: all
           tasks:
             - name: Dump commit message
               copy:
                 content: "{{ zuul.message | b64decode }}"
                 dest: "{{ zuul.executor.log_root }}/commit-message.txt"


Branch Items
~~~~~~~~~~~~

This represents a branch tip.  This item may have been enqueued
because the branch was updated (via a change having merged, or a
direct push).  Or it may have been enqueued by a timer for the purpose
of verifying the current condition of the branch.  The following
additional variables are available:

.. var:: zuul
   :hidden:

   .. var:: branch

      The name of the item's branch (without the `refs/heads/`
      prefix).

   .. var:: oldrev

      If the item was enqueued as the result of a change merging or
      being pushed to the branch, the git sha of the old revision will
      be included here.  Otherwise, this variable will be undefined.

   .. var:: newrev

      If the item was enqueued as the result of a change merging or
      being pushed to the branch, the git sha of the new revision will
      be included here.  Otherwise, this variable will be undefined.

Tag Items
~~~~~~~~~

This represents a git tag.  The item may have been enqueued because a
tag was created or deleted.  The following additional variables are
available:

.. var:: zuul
   :hidden:

   .. var:: tag

      The name of the item's tag (without the `refs/tags/` prefix).

   .. var:: oldrev

      If the item was enqueued as the result of a tag being deleted,
      the previous git sha of the tag will be included here.  If the
      tag was created, this variable will be undefined.

   .. var:: newrev

      If the item was enqueued as the result of a tag being created,
      the new git sha of the tag will be included here.  If the tag
      was deleted, this variable will be undefined.

Ref Items
~~~~~~~~~

This represents a git reference that is neither a change, branch, or
tag.  Note that all items include a `ref` attribute which may be used
to identify the ref.  The following additional variables are
available:

.. var:: zuul
   :hidden:

   .. var:: oldrev

      If the item was enqueued as the result of a ref being deleted,
      the previous git sha of the ref will be included here.  If the
      ref was created, this variable will be undefined.

   .. var:: newrev

      If the item was enqueued as the result of a ref being created,
      the new git sha of the ref will be included here.  If the ref
      was deleted, this variable will be undefined.

Working Directory
~~~~~~~~~~~~~~~~~

Additionally, some information about the working directory and the
executor running the job is available:

.. var:: zuul
   :hidden:

   .. var:: executor

      A number of values related to the executor running the job are
      available:

      .. var:: hostname

         The hostname of the executor.

      .. var:: src_root

         The path to the source directory.

      .. var:: log_root

         The path to the logs directory.

      .. var:: work_root

         The path to the working directory.

      .. var:: inventory_file

         The path to the inventory. This variable is needed for jobs running
         without a nodeset since Ansible doesn't set it for localhost; see
         this `porting guide
         <https://docs.ansible.com/ansible/latest/porting_guides/porting_guide_2.4.html#inventory>`_.

         The inventory file is only readable by jobs running in a
         :term:`trusted execution context`.

SSH Keys
--------

Zuul starts each job with an SSH agent running and at least one key
added to that agent.  Generally you won't need to be aware of this
since Ansible will use this when performing any tasks on remote nodes.
However, under some circumstances you may want to interact with the
agent.  For example, you may wish to add a key provided as a secret to
the job in order to access a specific host, or you may want to, in a
pre-playbook, replace the key used to log into the assigned nodes in
order to further protect it from being abused by untrusted job
content.

A description of each of the keys added to the SSH agent follows.

Nodepool Key
~~~~~~~~~~~~

This key is supplied by the system administrator.  It is expected to
be accepted by every node supplied by Nodepool and is generally the
key that will be used by Zuul when running jobs.  Because of the
potential for an unrelated job to add an arbitrary host to the Ansible
inventory which might accept this key (e.g., a node for another job,
or a static host), the use of the `add-build-sshkey
<https://zuul-ci.org/docs/zuul-jobs/roles.html#role-add-build-sshkey>`
role is recommended.

Project Key
~~~~~~~~~~~

Each project in Zuul has its own SSH keypair.  This key is added to
the SSH agent for all jobs running in a post-review pipeline.  If a
system administrator trusts that project, they can add the project's
public key to systems to allow post-review jobs to access those
systems.  The systems may be added to the inventory using the
``add_host`` Ansible module, or they may be supplied by static nodes
in Nodepool.

Zuul serves each project's public SSH key using its build-in
webserver.  They can be fetched at the path
``/api/tenant/<tenant>/project-ssh-key/<project>.pub`` where
``<project>`` is the canonical name of a project and ``<tenant>`` is
the name of a tenant with that project.

.. _return_values:

Return Values
-------------

A job may return some values to Zuul to affect its behavior and for
use by child jobs.  To return a value, use the ``zuul_return``
Ansible module in a job playbook.
For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          foo: bar

Will return the dictionary ``{'foo': 'bar'}`` to Zuul.

.. TODO: xref to section describing formatting

Any values other than those in the ``zuul`` hierarchy will be supplied
as Ansible variables to child jobs.  These variables have less
precedence than any other type of variable in Zuul, so be sure their
names are not shared by any job variables.  If more than one parent
job returns the same variable, the value from the later job in the job
graph will take precedence.

The values in the ``zuul`` hierarchy are special variables that influence the
behavior of zuul itself. The following paragraphs describe the currently
supported special variables and their meaning.

Returning the log url
~~~~~~~~~~~~~~~~~~~~~

To set the log URL for a build, use *zuul_return* to set the
**zuul.log_url** value.  For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          zuul:
            log_url: http://logs.example.com/path/to/build/logs

.. _return_artifacts:

Returning artifact URLs
~~~~~~~~~~~~~~~~~~~~~~~

If a build produces artifacts, any number of URLs may be returned to
Zuul and stored in the SQL database.  These will then be available via
the web interface and subsequent jobs.

To provide artifact URLs for a build, use *zuul_return* to set keys
under the **zuul.artifacts** dictionary.  For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          zuul:
            artifacts:
              - name: tarball
                url: http://example.com/path/to/package.tar.gz
                metadata:
                  version: 3.0
              - name: docs:
                url: build/docs/

If the value of **url** is a relative URL, it will be combined with
the **zuul.log_url** value if set to create an absolute URL.  The
**metadata** key is optional; if it is provided, it must be a
dictionary; its keys and values may be anything.

If *zuul_return* is invoked multiple times (e.g., via multiple
playbooks), then the elements of **zuul.artifacts** from each
invocation will be appended.

Skipping child jobs
~~~~~~~~~~~~~~~~~~~

To skip a child job for the current build, use *zuul_return* to set the
:var:`zuul.child_jobs` value. For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          zuul:
            child_jobs:
              - child_jobA
              - child_jobC

Will tell zuul to only run the child_jobA and child_jobC for pre-configured
child jobs. If child_jobB was configured, it would be now marked as SKIPPED. If
zuul.child_jobs is empty, all jobs will be marked as SKIPPED. Invalid child jobs
are stripped and ignored, if only invalid jobs are listed it is the same as
providing an empty list to zuul.child_jobs.

Leaving file comments
~~~~~~~~~~~~~~~~~~~~~

To instruct the reporters to leave line comments on files in the
change, set the **zuul.file_comments** value.  For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          zuul:
            file_comments:
              path/to/file.py:
                - line: 42
                  message: "Line too long"
                - line: 82
                  message: "Line too short"
                - line: 119
                  message: "This block is indented too far."
                  range:
                    start_line: 117
                    start_character:    0
                    end_line:   119
                    end_character:  37

Not all reporters currently support line comments (or all of the
features of line comments); in these cases, reporters will simply
ignore this data.

Zuul will attempt to automatically translate the supplied line numbers
to the corresponding lines in the original change as written (they may
differ due to other changes which may have merged since the change was
written).  If this produces erroneous results for a job, the behavior
may be disabled by setting the
**zuul.disable_file_comment_line_mapping** variable to ``true`` in
*zuul_return*.

Pausing the job
~~~~~~~~~~~~~~~

A job can be paused after the run phase. In this case the child jobs can start
and the parent job stays paused until all child jobs are finished. This for
example can be useful to start a docker registry in a parent job that will be
used by the child job. To indicate that the job should be paused use
*zuul_return* to set the **zuul.pause** value. You still can at the same time
supply any arbitrary data to the child jobs. For example:

.. code-block:: yaml

  tasks:
    - zuul_return:
        data:
          zuul:
            pause: true
          registry_ip_address: "{{ hostvars[groups.all[0]].ansible_host }}"


.. _build_status:

Build Status
------------

A job build may have the following status:

**SUCCESS**
  nominal job execution

**FAILURE**
  job executed correctly, but exited with a failure

**RETRY_LIMIT**
  the ``pre-run`` playbook failed more than the maximum number of
  retry ``attempts``.

**POST_FAILURE**
  the ``post-run`` playbook failed.

**SKIPPED**
  one of the build dependencies failed and this job was not executed.

**NODE_FAILURE**
  the test instance provider was unable to fullfill the nodeset
  request.  Note: this can happen if the Nodepool quota is exceeding
  the provider capacity, resulting in ``ERROR server creation: "No valid
  host found"``.
