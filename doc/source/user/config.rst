:title: Project Configuration

.. _project-config:

Project Configuration
=====================

The following sections describe the main part of Zuul's configuration.
All of what follows is found within files inside of the repositories
that Zuul manages.

Security Contexts
-----------------

When a system administrator configures Zuul to operate on a project,
they specify one of two security contexts for that project.  A
*config-project* is one which is primarily tasked with holding
configuration information and job content for Zuul.  Jobs which are
defined in a config-project are run with elevated privileges, and all
Zuul configuration items are available for use.  Base jobs (that is,
jobs without a parent) may only be defined in config-projects.  It is
expected that changes to config-projects will undergo careful scrutiny
before being merged.

An *untrusted-project* is a project whose primary focus is not to
operate Zuul, but rather it is one of the projects being tested or
deployed.  The Zuul configuration language available to these projects
is somewhat restricted (as detailed in individual sections below), and
jobs defined in these projects run in a restricted execution
environment since they may be operating on changes which have not yet
undergone review.

Configuration Loading
---------------------

When Zuul starts, it examines all of the git repositories which are
specified by the system administrator in :ref:`tenant-config` and
searches for files in the root of each repository. Zuul looks first
for a file named ``zuul.yaml`` or a directory named ``zuul.d``, and if
they are not found, ``.zuul.yaml`` or ``.zuul.d`` (with a leading
dot). In the case of an :term:`untrusted-project`, the configuration
from every branch is included, however, in the case of a
:term:`config-project`, only the ``master`` branch is examined.

When a change is proposed to one of these files in an
untrusted-project, the configuration proposed in the change is merged
into the running configuration so that any changes to Zuul's
configuration are self-testing as part of that change.  If there is a
configuration error, no jobs will be run and the error will be
reported by any applicable pipelines.  In the case of a change to a
config-project, the new configuration is parsed and examined for
errors, but the new configuration is not used in testing the change.
This is because configuration in config-projects is able to access
elevated privileges and should always be reviewed before being merged.

As soon as a change containing a Zuul configuration change merges to
any Zuul-managed repository, the new configuration takes effect
immediately.

.. _configuration-items:

Configuration Items
-------------------

The ``zuul.yaml`` and ``.zuul.yaml`` configuration files are
YAML-formatted and are structured as a series of items, each of which
is described below.

In the case of a ``zuul.d`` directory, Zuul recurses the directory and
extends the configuration using all the .yaml files in the sorted path
order.  For example, to keep job's variants in a separate file, it
needs to be loaded after the main entries, for example using number
prefixes in file's names::

* zuul.d/pipelines.yaml
* zuul.d/projects.yaml
* zuul.d/01_jobs.yaml
* zuul.d/02_jobs-variants.yaml

.. _pipeline:

Pipeline
~~~~~~~~

A pipeline describes a workflow operation in Zuul.  It associates jobs
for a given project with triggering and reporting events.

Its flexible configuration allows for characterizing any number of
workflows, and by specifying each as a named configuration, makes it
easy to apply similar workflow operations to projects or groups of
projects.

By way of example, one of the primary uses of Zuul is to perform
project gating.  To do so, one can create a :term:`gate` pipeline
which tells Zuul that when a certain event (such as approval by a code
reviewer) occurs, the corresponding change or pull request should be
enqueued into the pipeline.  When that happens, the jobs which have
been configured to run for that project in the gate pipeline are run,
and when they complete, the pipeline reports the results to the user.

Pipeline configuration items may only appear in :term:`config-projects
<config-project>`.

Generally, a Zuul administrator would define a small number of
pipelines which represent the workflow processes used in their
environment.  Each project can then be added to the available
pipelines as appropriate.

Here is an example :term:`check` pipeline, which runs whenever a new
patchset is created in Gerrit.  If the associated jobs all report
success, the pipeline reports back to Gerrit with ``Verified`` vote of
+1, or if at least one of them fails, a -1:

.. code-block:: yaml

   - pipeline:
       name: check
       manager: independent
       trigger:
         my_gerrit:
           - event: patchset-created
       success:
         my_gerrit:
           Verified: 1
       failure:
         my_gerrit
           Verified: -1

.. TODO: See TODO for more annotated examples of common pipeline configurations.

.. attr:: pipeline

   The attributes available on a pipeline are as follows (all are
   optional unless otherwise specified):

   .. attr:: name
      :required:

      This is used later in the project definition to indicate what jobs
      should be run for events in the pipeline.

   .. attr:: manager
      :required:

      There are currently two schemes for managing pipelines:

      .. value:: independent

         Every event in this pipeline should be treated as independent
         of other events in the pipeline.  This is appropriate when
         the order of events in the pipeline doesn't matter because
         the results of the actions this pipeline performs can not
         affect other events in the pipeline.  For example, when a
         change is first uploaded for review, you may want to run
         tests on that change to provide early feedback to reviewers.
         At the end of the tests, the change is not going to be
         merged, so it is safe to run these tests in parallel without
         regard to any other changes in the pipeline.  They are
         independent.

         Another type of pipeline that is independent is a post-merge
         pipeline. In that case, the changes have already merged, so
         the results can not affect any other events in the pipeline.

      .. value:: dependent

         The dependent pipeline manager is designed for gating.  It
         ensures that every change is tested exactly as it is going to
         be merged into the repository.  An ideal gating system would
         test one change at a time, applied to the tip of the
         repository, and only if that change passed tests would it be
         merged.  Then the next change in line would be tested the
         same way.  In order to achieve parallel testing of changes,
         the dependent pipeline manager performs speculative execution
         on changes.  It orders changes based on their entry into the
         pipeline.  It begins testing all changes in parallel,
         assuming that each change ahead in the pipeline will pass its
         tests.  If they all succeed, all the changes can be tested
         and merged in parallel.  If a change near the front of the
         pipeline fails its tests, each change behind it ignores
         whatever tests have been completed and are tested again
         without the change in front.  This way gate tests may run in
         parallel but still be tested correctly, exactly as they will
         appear in the repository when merged.

         For more detail on the theory and operation of Zuul's
         dependent pipeline manager, see: :doc:`gating`.

   .. attr:: post-review
      :default: false

      This is a boolean which indicates that this pipeline executes
      code that has been reviewed.  Some jobs perform actions which
      should not be permitted with unreviewed code.  When this value
      is ``false`` those jobs will not be permitted to run in the
      pipeline.  If a pipeline is designed only to be used after
      changes are reviewed or merged, set this value to ``true`` to
      permit such jobs.

      For more information, see :ref:`secret` and
      :attr:`job.post-review`.

   .. attr:: description

      This field may be used to provide a textual description of the
      pipeline.  It may appear in the status page or in documentation.

   .. attr:: success-message
      :default: Build successful.

      The introductory text in reports when all the voting jobs are
      successful.

   .. attr:: failure-message
      :default: Build failed.

      The introductory text in reports when at least one voting job
      fails.

   .. attr:: merge-failure-message
      :default: Merge failed.

      The introductory text in the message reported when a change
      fails to merge with the current state of the repository.
      Defaults to "Merge failed."

   .. attr:: footer-message

      Supplies additional information after test results.  Useful for
      adding information about the CI system such as debugging and
      contact details.

   .. attr:: trigger

      At least one trigger source must be supplied for each pipeline.
      Triggers are not exclusive -- matching events may be placed in
      multiple pipelines, and they will behave independently in each
      of the pipelines they match.

      Triggers are loaded from their connection name. The driver type
      of the connection will dictate which options are available.  See
      :ref:`drivers`.

   .. attr:: require

      If this section is present, it establishes prerequisites for
      any kind of item entering the Pipeline.  Regardless of how the
      item is to be enqueued (via any trigger or automatic dependency
      resolution), the conditions specified here must be met or the
      item will not be enqueued.  These requirements may vary
      depending on the source of the item being enqueued.

      Requirements are loaded from their connection name. The driver
      type of the connection will dictate which options are available.
      See :ref:`drivers`.

   .. attr:: reject

      If this section is present, it establishes prerequisites that
      can block an item from being enqueued. It can be considered a
      negative version of :attr:`pipeline.require`.

      Requirements are loaded from their connection name. The driver
      type of the connection will dictate which options are available.
      See :ref:`drivers`.

   .. attr:: dequeue-on-new-patchset
      :default: true

      Normally, if a new patchset is uploaded to a change that is in a
      pipeline, the existing entry in the pipeline will be removed
      (with jobs canceled and any dependent changes that can no longer
      merge as well.  To suppress this behavior (and allow jobs to
      continue running), set this to ``false``.

   .. attr:: ignore-dependencies
      :default: false

      In any kind of pipeline (dependent or independent), Zuul will
      attempt to enqueue all dependencies ahead of the current change
      so that they are tested together (independent pipelines report
      the results of each change regardless of the results of changes
      ahead).  To ignore dependencies completely in an independent
      pipeline, set this to ``true``.  This option is ignored by
      dependent pipelines.

   .. attr:: precedence
      :default: normal

      Indicates how the build scheduler should prioritize jobs for
      different pipelines.  Each pipeline may have one precedence,
      jobs for pipelines with a higher precedence will be run before
      ones with lower.  The value should be one of ``high``,
      ``normal``, or ``low``.  Default: ``normal``.

   .. _reporters:

   The following options configure :term:`reporters <reporter>`.
   Reporters are complementary to triggers; where a trigger is an
   event on a connection which causes Zuul to enqueue an item, a
   reporter is the action performed on a connection when an item is
   dequeued after its jobs complete.  The actual syntax for a reporter
   is defined by the driver which implements it.  See :ref:`drivers`
   for more information.

   .. attr:: success

      Describes where Zuul should report to if all the jobs complete
      successfully.  This section is optional; if it is omitted, Zuul
      will run jobs and do nothing on success -- it will not report at
      all.  If the section is present, the listed :term:`reporters
      <reporter>` will be asked to report on the jobs.  The reporters
      are listed by their connection name. The options available
      depend on the driver for the supplied connection.

   .. attr:: failure

      These reporters describe what Zuul should do if at least one job
      fails.

   .. attr:: merge-failure

      These reporters describe what Zuul should do if it is unable to
      merge in the patchset. If no merge-failure reporters are listed
      then the ``failure`` reporters will be used to notify of
      unsuccessful merges.

   .. attr:: start

      These reporters describe what Zuul should do when a change is
      added to the pipeline.  This can be used, for example, to reset
      a previously reported result.

   .. attr:: disabled

      These reporters describe what Zuul should do when a pipeline is
      disabled.  See ``disable-after-consecutive-failures``.

   The following options can be used to alter Zuul's behavior to
   mitigate situations in which jobs are failing frequently (perhaps
   due to a problem with an external dependency, or unusually high
   non-deterministic test failures).

   .. attr:: disable-after-consecutive-failures

      If set, a pipeline can enter a *disabled* state if too many
      changes in a row fail. When this value is exceeded the pipeline
      will stop reporting to any of the **success**, **failure** or
      **merge-failure** reporters and instead only report to the
      **disabled** reporters.  (No **start** reports are made when a
      pipeline is disabled).

   .. attr:: window
      :default: 20

      Dependent pipeline managers only. Zuul can rate limit dependent
      pipelines in a manner similar to TCP flow control.  Jobs are
      only started for items in the queue if they are within the
      actionable window for the pipeline. The initial length of this
      window is configurable with this value. The value given should
      be a positive integer value. A value of ``0`` disables rate
      limiting on the :value:`dependent pipeline manager
      <pipeline.manager.dependent>`.

   .. attr:: window-floor
      :default: 3

      Dependent pipeline managers only. This is the minimum value for
      the window described above. Should be a positive non zero
      integer value.

   .. attr:: window-increase-type
      :default: linear

      Dependent pipeline managers only. This value describes how the
      window should grow when changes are successfully merged by zuul.

      .. value:: linear

         Indicates that **window-increase-factor** should be added to
         the previous window value.

      .. value:: exponential

         Indicates that **window-increase-factor** should be
         multiplied against the previous window value and the result
         will become the window size.

   .. attr:: window-increase-factor
      :default: 1

      Dependent pipeline managers only. The value to be added or
      multiplied against the previous window value to determine the
      new window after successful change merges.

   .. attr:: window-decrease-type
      :default: exponential

      Dependent pipeline managers only. This value describes how the
      window should shrink when changes are not able to be merged by
      Zuul.

      .. value:: linear

         Indicates that **window-decrease-factor** should be
         subtracted from the previous window value.

      .. value:: exponential

         Indicates that **window-decrease-factor** should be divided
         against the previous window value and the result will become
         the window size.

   .. attr:: window-decrease-factor
      :default: 2

      :value:`Dependent pipeline managers
      <pipeline.manager.dependent>` only. The value to be subtracted
      or divided against the previous window value to determine the
      new window after unsuccessful change merges.


.. _job:

Job
~~~

A job is a unit of work performed by Zuul on an item enqueued into a
pipeline.  Items may run any number of jobs (which may depend on each
other).  Each job is an invocation of an Ansible playbook with a
specific inventory of hosts.  The actual tasks that are run by the job
appear in the playbook for that job while the attributes that appear in the
Zuul configuration specify information about when, where, and how the
job should be run.

Jobs in Zuul support inheritance.  Any job may specify a single parent
job, and any attributes not set on the child job are collected from
the parent job.  In this way, a configuration structure may be built
starting with very basic jobs which describe characteristics that all
jobs on the system should have, progressing through stages of
specialization before arriving at a particular job.  A job may inherit
from any other job in any project (however, if the other job is marked
as :attr:`job.final`, jobs may not inherit from it).

A job with no parent is called a *base job* and may only be defined in
a :term:`config-project`.  Every other job must have a parent, and so
ultimately, all jobs must have an inheritance path which terminates at
a base job.  Each tenant has a default parent job which will be used
if no explicit parent is specified.

Multiple job definitions with the same name are called variants.
These may have different selection criteria which indicate to Zuul
that, for instance, the job should behave differently on a different
git branch.  Unlike inheritance, all job variants must be defined in
the same project.  Some attributes of jobs marked :attr:`job.final`
may not be overidden

When Zuul decides to run a job, it performs a process known as
freezing the job.  Because any number of job variants may be
applicable, Zuul collects all of the matching variants and applies
them in the order they appeared in the configuration.  The resulting
frozen job is built from attributes gathered from all of the
matching variants.  In this way, exactly what is run is dependent on
the pipeline, project, branch, and content of the item.

In addition to the job's main playbook, each job may specify one or
more pre- and post-playbooks.  These are run, in order, before and
after (respectively) the main playbook.  They may be used to set up
and tear down resources needed by the main playbook.  When combined
with inheritance, they provide powerful tools for job construction.  A
job only has a single main playbook, and when inheriting from a
parent, the child's main playbook overrides (or replaces) the
parent's.  However, the pre- and post-playbooks are appended and
prepended in a nesting fashion.  So if a parent job and child job both
specified pre and post playbooks, the sequence of playbooks run would
be:

* parent pre-run playbook
* child pre-run playbook
* child playbook
* child post-run playbook
* parent post-run playbook

Further inheritance would nest even deeper.

Here is an example of two job definitions:

.. code-block:: yaml

   - job:
       name: base
       pre-run: copy-git-repos
       post-run: copy-logs

   - job:
       name: run-tests
       parent: base
       nodeset:
         nodes:
           - name: test-node
             label: fedora

.. attr:: job

   The following attributes are available on a job; all are optional
   unless otherwise specified:

   .. attr:: name
      :required:

      The name of the job.  By default, Zuul looks for a playbook with
      this name to use as the main playbook for the job.  This name is
      also referenced later in a project pipeline configuration.

   .. TODO: figure out how to link the parent default to tenant.default.parent

   .. attr:: parent
      :default: Tenant default-parent

      Specifies a job to inherit from.  The parent job can be defined
      in this or any other project.  Any attributes not specified on a
      job will be collected from its parent.  If no value is supplied
      here, the job specified by :attr:`tenant.default-parent` will be
      used.  If **parent** is set to ``null`` (which is only valid in
      a :term:`config-project`), this is a :term:`base job`.

   .. attr:: description

      A textual description of the job.  Not currently used directly
      by Zuul, but it is used by the zuul-sphinx extension to Sphinx
      to auto-document Zuul jobs (in which case it is interpreted as
      ReStructuredText.

   .. attr:: final
      :default: false

      To prevent other jobs from inheriting from this job, and also to
      prevent changing execution-related attributes when this job is
      specified in a project's pipeline, set this attribute to
      ``true``.

   .. attr:: success-message
      :default: SUCCESS

      Normally when a job succeeds, the string ``SUCCESS`` is reported
      as the result for the job.  If set, this option may be used to
      supply a different string.

   .. attr:: failure-message
      :default: FAILURE

      Normally when a job fails, the string ``FAILURE`` is reported as
      the result for the job.  If set, this option may be used to
      supply a different string.

   .. attr:: success-url

      When a job succeeds, this URL is reported along with the result.
      If this value is not supplied, Zuul uses the content of the job
      :ref:`return value <return_values>` **zuul.log_url**.  This is
      recommended as it allows the code which stores the URL to the
      job artifacts to report exactly where they were stored.  To
      override this value, or if it is not set, supply an absolute URL
      in this field.  If a relative URL is supplied in this field, and
      **zuul.log_url** is set, then the two will be combined to
      produce the URL used for the report.  This can be used to
      specify that certain jobs should "deep link" into the stored job
      artifacts.

   .. attr:: failure-url

      When a job fails, this URL is reported along with the result.
      Otherwise behaves the same as **success-url**.

   .. attr:: hold-following-changes
      :default: false

      In a dependent pipeline, this option may be used to indicate
      that no jobs should start on any items which depend on the
      current item until this job has completed successfully.  This
      may be used to conserve build resources, at the expense of
      inhibiting the parallelization which speeds the processing of
      items in a dependent pipeline.

   .. attr:: voting
      :default: true

      Indicates whether the result of this job should be used in
      determining the overall result of the item.

   .. attr:: semaphore

      The name of a :ref:`semaphore` which should be acquired and
      released when the job begins and ends.  If the semaphore is at
      maximum capacity, then Zuul will wait until it can be acquired
      before starting the job.

   .. attr:: tags

      Metadata about this job.  Tags are units of information attached
      to the job; they do not affect Zuul's behavior, but they can be
      used within the job to characterize the job.  For example, a job
      which tests a certain subsystem could be tagged with the name of
      that subsystem, and if the job's results are reported into a
      database, then the results of all jobs affecting that subsystem
      could be queried.  This attribute is specified as a list of
      strings, and when inheriting jobs or applying variants, tags
      accumulate in a set, so the result is always a set of all the
      tags from all the jobs and variants used in constructing the
      frozen job, with no duplication.

   .. attr:: branches

      A regular expression (or list of regular expressions) which
      describe on what branches a job should run (or in the case of
      variants: to alter the behavior of a job for a certain branch).

      If there is no job definition for a given job which matches the
      branch of an item, then that job is not run for the item.
      Otherwise, all of the job variants which match that branch (and
      any other selection criteria) are used when freezing the job.

      This example illustrates a job called *run-tests* which uses a
      nodeset based on the current release of an operating system to
      perform its tests, except when testing changes to the stable/2.0
      branch, in which case it uses an older release:

      .. code-block:: yaml

         - job:
             name: run-tests
             nodeset: current-release

         - job:
             name: run-tests
             branches: stable/2.0
             nodeset: old-release

      In some cases, Zuul uses an implied value for the branch
      specifier if none is supplied:

      * For a job definition in a :term:`config-project`, no implied
        branch specifier is used.  If no branch specifier appears, the
        job applies to all branches.

      * In the case of an :term:`untrusted-project`, if the project
        has only one branch, no implied branch specifier is applied to
        :ref:`job` definitions.  If the project has more than one
        branch, the branch containing the job definition is used as an
        implied branch specifier.

      * In the case of a job variant defined within a :ref:`project`,
        if the project definition is in a :term:`config-project`, no
        implied branch specifier is used.  If it appears in an
        :term:`untrusted-project`, with no branch specifier, the
        branch containing the project definition is used as an implied
        branch specifier.

      * In the case of a job variant defined within a
        :ref:`project-template`, if no branch specifier appears, the
        implied branch containing the project-template definition is
        used as an implied branch specifier.  This means that
        definitions of the same project-template on different branches
        may run different jobs.

        When that project-template is used by a :ref:`project`
        definition within a :term:`untrusted-project`, the branch
        containing that project definition is combined with the branch
        specifier of the project-template.  This means it is possible
        for a project to use a template on one branch, but not on
        another.

      This allows for the very simple and expected workflow where if a
      project defines a job on the ``master`` branch with no branch
      specifier, and then creates a new branch based on ``master``,
      any changes to that job definition within the new branch only
      affect that branch, and likewise, changes to the master branch
      only affect it.

      See :attr:`pragma.implied-branch-matchers` for how to override
      this behavior on a per-file basis.

   .. attr:: files

      This attribute indicates that the job should only run on changes
      where the specified files are modified.  This is a regular
      expression or list of regular expressions.

   .. attr:: irrelevant-files

      This is a negative complement of **files**.  It indicates that
      the job should run unless *all* of the files changed match this
      list.  In other words, if the regular expression ``docs/.*`` is
      supplied, then this job will not run if the only files changed
      are in the docs directory.  A regular expression or list of
      regular expressions.

   .. attr:: secrets

      A list of secrets which may be used by the job.  A
      :ref:`secret` is a named collection of private information
      defined separately in the configuration.  The secrets that
      appear here must be defined in the same project as this job
      definition.

      Each item in the list may may be supplied either as a string,
      in which case it references the name of a :ref:`secret` definition,
      or as a dict. If an element in this list is given as a dict, it
      must have the following fields.

      .. attr:: name

         The name to use for the Ansible variable into which the secret
         content will be placed.

      .. attr:: secret

         The name to use to find the secret's definition in the configuration.

      For example:

      .. code-block:: yaml

         - secret:
             important-secret:
               key: encrypted-secret-key-data

         - job:
             name: amazing-job:
             secrets:
               - name: ssh_key
                 secret: important-secret

      will result in the following being passed as a variable to the playbooks
      in ``amazing-job``:

      .. code-block:: yaml

         ssh_key:
           key: descrypted-secret-key-data

   .. attr:: nodeset

      The nodes which should be supplied to the job.  This parameter
      may be supplied either as a string, in which case it references
      a :ref:`nodeset` definition which appears elsewhere in the
      configuration, or a dictionary, in which case it is interpreted
      in the same way as a Nodeset definition, though the ``name``
      attribute should be omitted (in essence, it is an anonymous
      Nodeset definition unique to this job).  See the :ref:`nodeset`
      reference for the syntax to use in that case.

      If a job has an empty or no nodeset definition, it will still
      run and may be able to perform actions on the Zuul executor.

   .. attr:: override-checkout

      When Zuul runs jobs for a proposed change, it normally checks
      out the branch associated with that change on every project
      present in the job.  If jobs are running on a ref (such as a
      branch tip or tag), then that ref is normally checked out.  This
      attribute is used to override that behavior and indicate that
      this job should, regardless of the branch for the queue item,
      use the indicated ref (i.e., branch or tag) instead.  This can
      be used, for example, to run a previous version of the software
      (from a stable maintenance branch) under test even if the change
      being tested applies to a different branch (this is only likely
      to be useful if there is some cross-branch interaction with some
      component of the system being tested).  See also the
      project-specific :attr:`job.required-projects.override-checkout`
      attribute to apply this behavior to a subset of a job's
      projects.

   .. attr:: timeout

      The time in seconds that the job should be allowed to run before
      it is automatically aborted and failure is reported.  If no
      timeout is supplied, the job may run indefinitely.  Supplying a
      timeout is highly recommended.

   .. attr:: attempts
      :default: 3

      When Zuul encounters an error running a job's pre-run playbook,
      Zuul will stop and restart the job.  Errors during the main or
      post-run -playbook phase of a job are not affected by this
      parameter (they are reported immediately).  This parameter
      controls the number of attempts to make before an error is
      reported.

   .. attr:: pre-run

      The name of a playbook or list of playbooks to run before the
      main body of a job.  The full path to the playbook in the repo
      where the job is defined is expected.

      When a job inherits from a parent, the child's pre-run playbooks
      are run after the parent's.  See :ref:`job` for more
      information.

   .. attr:: post-run

      The name of a playbook or list of playbooks to run after the
      main body of a job.  The full path to the playbook in the repo
      where the job is defined is expected.

      When a job inherits from a parent, the child's post-run
      playbooks are run before the parent's.  See :ref:`job` for more
      information.

   .. attr:: run

      The name of the main playbook for this job.  If it is not
      supplied, the parent's playbook will be used (and likewise up
      the inheritance chain).  The full path within the repo is
      required.  Example:

      .. code-block:: yaml

         run: playbooks/job-playbook.yaml

   .. attr:: roles

      A list of Ansible roles to prepare for the job.  Because a job
      runs an Ansible playbook, any roles which are used by the job
      must be prepared and installed by Zuul before the job begins.
      This value is a list of dictionaries, each of which indicates
      one of two types of roles: a Galaxy role, which is simply a role
      that is installed from Ansible Galaxy, or a Zuul role, which is
      a role provided by a project managed by Zuul.  Zuul roles are
      able to benefit from speculative merging and cross-project
      dependencies when used by playbooks in untrusted projects.
      Roles are added to the Ansible role path in the order they
      appear on the job -- roles earlier in the list will take
      precedence over those which follow.

      In the case of job inheritance or variance, the roles used for
      each of the playbooks run by the job will be only those which
      were defined along with that playbook.  If a child job inherits
      from a parent which defines a pre and post playbook, then the
      pre and post playbooks it inherits from the parent job will run
      only with the roles that were defined on the parent.  If the
      child adds its own pre and post playbooks, then any roles added
      by the child will be available to the child's playbooks.  This
      is so that a job which inherits from a parent does not
      inadvertently alter the behavior of the parent's playbooks by
      the addition of conflicting roles.  Roles added by a child will
      appear before those it inherits from its parent.

      A project which supplies a role may be structured in one of two
      configurations: a bare role (in which the role exists at the
      root of the project), or a contained role (in which the role
      exists within the ``roles/`` directory of the project, perhaps
      along with other roles).  In the case of a contained role, the
      ``roles/`` directory of the project is added to the role search
      path.  In the case of a bare role, the project itself is added
      to the role search path.  In case the name of the project is not
      the name under which the role should be installed (and therefore
      referenced from Ansible), the ``name`` attribute may be used to
      specify an alternate.

      A job automatically has the project in which it is defined added
      to the roles path if that project appears to contain a role or
      ``roles/`` directory.  By default, the project is added to the
      path under its own name, however, that may be changed by
      explicitly listing the project in the roles list in the usual
      way.

      .. note:: Galaxy roles are not yet implemented.

      .. attr:: galaxy

         The name of the role in Ansible Galaxy.  If this attribute is
         supplied, Zuul will search Ansible Galaxy for a role by this
         name and install it.  Mutually exclusive with ``zuul``;
         either ``galaxy`` or ``zuul`` must be supplied.

      .. attr:: zuul

         The name of a Zuul project which supplies the role.  Mutually
         exclusive with ``galaxy``; either ``galaxy`` or ``zuul`` must
         be supplied.

      .. attr:: name

         The installation name of the role.  In the case of a bare
         role, the role will be made available under this name.
         Ignored in the case of a contained role.

   .. attr:: required-projects

      A list of other projects which are used by this job.  Any Zuul
      projects specified here will also be checked out by Zuul into
      the working directory for the job.  Speculative merging and
      cross-repo dependencies will be honored.

      The format for this attribute is either a list of strings or
      dictionaries.  Strings are interpreted as project names,
      dictionaries, if used, may have the following attributes:

      .. attr:: name
         :required:

         The name of the required project.

      .. attr:: override-checkout

         When Zuul runs jobs for a proposed change, it normally checks
         out the branch associated with that change on every project
         present in the job.  If jobs are running on a ref (such as a
         branch tip or tag), then that ref is normally checked out.
         This attribute is used to override that behavior and indicate
         that this job should, regardless of the branch for the queue
         item, use the indicated ref (i.e., branch or tag) instead,
         for only this project.  See also the
         :attr:`job.override-checkout` attribute to apply the same
         behavior to all projects in a job.

   .. attr:: vars

      A dictionary of variables to supply to Ansible.  When inheriting
      from a job (or creating a variant of a job) vars are merged with
      previous definitions.  This means a variable definition with the
      same name will override a previously defined variable, but new
      variable names will be added to the set of defined variables.

   .. attr:: dependencies

      A list of other jobs upon which this job depends.  Zuul will not
      start executing this job until all of its dependencies have
      completed successfully, and if one or more of them fail, this
      job will not be run.

   .. attr:: allowed-projects

      A list of Zuul projects which may use this job.  By default, a
      job may be used by any other project known to Zuul, however,
      some jobs use resources or perform actions which are not
      appropriate for other projects.  In these cases, a list of
      projects which are allowed to use this job may be supplied.  If
      this list is not empty, then it must be an exhaustive list of
      all projects permitted to use the job.  The current project
      (where the job is defined) is not automatically included, so if
      it should be able to run this job, then it must be explicitly
      listed.  By default, all projects may use the job.

   .. attr:: post-review
      :default: false

      A boolean value which indicates whether this job may only be
      used in pipelines where :attr:`pipeline.post-review` is
      ``true``.  This is automatically set to ``true`` if this job
      uses a :ref:`secret` and is defined in a :term:`untrusted-project`.
      It may be explicitly set to obtain the same behavior for jobs
      defined in :term:`config projects <config-project>`.  Once this
      is set to ``true`` anywhere in the inheritance hierarchy for a job,
      it will remain set for all child jobs and variants (it can not be
      set to ``false``).

.. _project:

Project
~~~~~~~

A project corresponds to a source code repository with which Zuul is
configured to interact.  The main responsibility of the project
configuration item is to specify which jobs should run in which
pipelines for a given project.  Within each project definition, a
section for each :ref:`pipeline <pipeline>` may appear.  This
project-pipeline definition is what determines how a project
participates in a pipeline.

Multiple project definitions may appear for the same project (for
example, in a central :term:`config projects <config-project>` as well
as in a repo's own ``.zuul.yaml``).  In this case, all of the project
definitions are combined (the jobs listed in all of the definitions
will be run).

Consider the following project definition::

  - project:
      name: yoyodyne
      check:
        jobs:
          - check-syntax
          - unit-tests
      gate:
        queue: integrated
        jobs:
          - unit-tests
          - integration-tests

The project has two project-pipeline stanzas, one for the ``check``
pipeline, and one for ``gate``.  Each specifies which jobs should run
when a change for that project enters the respective pipeline -- when
a change enters ``check``, the ``check-syntax`` and ``unit-test`` jobs
are run.

Pipelines which use the dependent pipeline manager (e.g., the ``gate``
example shown earlier) maintain separate queues for groups of
projects.  When Zuul serializes a set of changes which represent
future potential project states, it must know about all of the
projects within Zuul which may have an effect on the outcome of the
jobs it runs.  If project *A* uses project *B* as a library, then Zuul
must be told about that relationship so that it knows to serialize
changes to A and B together, so that it does not merge a change to B
while it is testing a change to A.

Zuul could simply assume that all projects are related, or even infer
relationships by which projects a job indicates it uses, however, in a
large system that would become unwieldy very quickly, and
unnecessarily delay changes to unrelated projects.  To allow for
flexibility in the construction of groups of related projects, the
change queues used by dependent pipeline managers are specified
manually.  To group two or more related projects into a shared queue
for a dependent pipeline, set the ``queue`` parameter to the same
value for those projects.

The ``gate`` project-pipeline definition above specifies that this
project participates in the ``integrated`` shared queue for that
pipeline.

.. attr:: project

   The following attributes may appear in a project:

   .. attr:: name
      :required:

      The name of the project.  If Zuul is configured with two or more
      unique projects with the same name, the canonical hostname for
      the project should be included (e.g., `git.example.com/foo`).

   .. attr:: templates

      A list of :ref:`project-template` references; the
      project-pipeline definitions of each Project Template will be
      applied to this project.  If more than one template includes
      jobs for a given pipeline, they will be combined, as will any
      jobs specified in project-pipeline definitions on the project
      itself.

   .. attr:: merge-mode
      :default: merge-resolve

      The merge mode which is used by Git for this project.  Be sure
      this matches what the remote system which performs merges (i.e.,
      Gerrit or GitHub).  Must be one of the following values:

      .. value:: merge

         Uses the default git merge strategy (recursive).

      .. value:: merge-resolve

         Uses the resolve git merge strategy.  This is a very
         conservative merge strategy which most closely matches the
         behavior of Gerrit.

      .. value:: cherry-pick

         Cherry-picks each change onto the branch rather than
         performing any merges.

   .. attr:: <pipeline>

      Each pipeline that the project participates in should have an
      entry in the project.  The value for this key should be a
      dictionary with the following format:

      .. attr:: jobs
         :required:

         A list of jobs that should be run when items for this project
         are enqueued into the pipeline.  Each item of this list may
         be a string, in which case it is treated as a job name, or it
         may be a dictionary, in which case it is treated as a job
         variant local to this project and pipeline.  In that case,
         the format of the dictionary is the same as the top level
         :attr:`job` definition.  Any attributes set on the job here
         will override previous versions of the job.

      .. attr:: queue

         If this pipeline is a :value:`dependent
         <pipeline.manager.dependent>` pipeline, this specifies the
         name of the shared queue this project is in.  Any projects
         which interact with each other in tests should be part of the
         same shared queue in order to ensure that they don't merge
         changes which break the others.  This is a free-form string;
         just set the same value for each group of projects.

.. _project-template:

Project Template
~~~~~~~~~~~~~~~~

A Project Template defines one or more project-pipeline definitions
which can be re-used by multiple projects.

A Project Template uses the same syntax as a :ref:`project`
definition, however, in the case of a template, the
:attr:`project.name` attribute does not refer to the name of a
project, but rather names the template so that it can be referenced in
a `Project` definition.

.. _secret:

Secret
~~~~~~

A Secret is a collection of private data for use by one or more jobs.
In order to maintain the security of the data, the values are usually
encrypted, however, data which are not sensitive may be provided
unencrypted as well for convenience.

A Secret may only be used by jobs defined within the same project.  To
use a secret, a :ref:`job` must specify the secret in
:attr:`job.secrets`.  Secrets are bound to the playbooks associated
with the specific job definition where they were declared.  Additional
pre or post playbooks which appear in child jobs will not have access
to the secrets, nor will playbooks which override the main playbook
(if any) of the job which declared the secret.  This protects against
jobs in other repositories declaring a job with a secret as a parent
and then exposing that secret.

It is possible to use secrets for jobs defined in :term:`config
projects <config-project>` as well as :term:`untrusted projects
<untrusted-project>`, however their use differs slightly.  Because
playbooks in a config project which use secrets run in the
:term:`trusted execution context` where proposed changes are not used
in executing jobs, it is safe for those secrets to be used in all
types of pipelines.  However, because playbooks defined in an
untrusted project are run in the :term:`untrusted execution context`
where proposed changes are used in job execution, it is dangerous to
allow those secrets to be used in pipelines which are used to execute
proposed but unreviewed changes.  By default, pipelines are considered
`pre-review` and will refuse to run jobs which have playbooks that use
secrets in the untrusted execution context to protect against someone
proposing a change which exposes a secret.  To permit this (for
instance, in a pipeline which only runs after code review), the
:attr:`pipeline.post-review` attribute may be explicitly set to
``true``.

In some cases, it may be desirable to prevent a job which is defined
in a config project from running in a pre-review pipeline (e.g., a job
used to publish an artifact).  In these cases, the
:attr:`job.post-review` attribute may be explicitly set to ``true`` to
indicate the job should only run in post-review pipelines.

If a job with secrets is unsafe to be used by other projects, the
`allowed-projects` job attribute can be used to restrict the projects
which can invoke that job.

.. attr:: secret

   The following attributes must appear on a secret:

   .. attr:: name
      :required:

      The name of the secret, used in a :ref:`Job` definition to
      request the secret.

   .. attr:: data
      :required:

      A dictionary which will be added to the Ansible variables
      available to the job.  The values can either be plain text
      strings, or encrypted values.  See :ref:`encryption` for more
      information.

.. _nodeset:

Nodeset
~~~~~~~

A Nodeset is a named collection of nodes for use by a job.  Jobs may
specify what nodes they require individually, however, by defining
groups of node types once and referring to them by name, job
configuration may be simplified.

.. code-block:: yaml

   - nodeset:
       name: nodeset1
       nodes:
         - name: controller
           label: controller-label
         - name: compute1
           label: compute-label
         - name:
             - compute2
             - web
           label: compute-label
       groups:
         - name: ceph-osd
           nodes:
             - controller
         - name: ceph-monitor
           nodes:
             - controller
             - compute1
             - compute2
          - name: ceph-web
            nodes:
              - web

.. attr:: nodeset

   A Nodeset requires two attributes:

   .. attr:: name
      :required:

      The name of the Nodeset, to be referenced by a :ref:`job`.

   .. attr:: nodes
      :required:

      A list of node definitions, each of which has the following format:

      .. attr:: name
         :required:

         The name of the node.  This will appear in the Ansible inventory
         for the job.

         This can also be as a list of strings. If so, then the list of hosts in
         the Ansible inventory will share a common ansible_host address.

      .. attr:: label
         :required:

         The Nodepool label for the node.  Zuul will request a node with
         this label.

   .. attr:: groups

      Additional groups can be defined which are accessible from the ansible
      playbooks.

      .. attr:: name
         :required:

         The name of the group to be referenced by an ansible playbook.

      .. attr:: nodes
         :required:

         The nodes that shall be part of the group. This is specified as a list
         of strings.

.. _semaphore:

Semaphore
~~~~~~~~~

Semaphores can be used to restrict the number of certain jobs which
are running at the same time.  This may be useful for jobs which
access shared or limited resources.  A semaphore has a value which
represents the maximum number of jobs which use that semaphore at the
same time.

Semaphores are never subject to dynamic reconfiguration.  If the value
of a semaphore is changed, it will take effect only when the change
where it is updated is merged.  An example follows:

.. code-block:: yaml

   - semaphore:
       name: semaphore-foo
       max: 5
   - semaphore:
       name: semaphore-bar
       max: 3

.. attr:: semaphore

   The following attributes are available:

   .. attr:: name
      :required:

      The name of the semaphore, referenced by jobs.

   .. attr:: max
      :default: 1

      The maximum number of running jobs which can use this semaphore.

.. _pragma:

Pragma
~~~~~~

The `pragma` item does not behave like the others.  It can not be
included or excluded from configuration loading by the administrator,
and does not form part of the final configuration itself.  It is used
to alter how the configuration is processed while loading.

A pragma item only affects the current file.  The same file in another
branch of the same project will not be affected, nor any other files
or any other projects.  The effect is global within that file --
pragma directives may not be set and then unset within the same file.

.. code-block:: yaml

   - pragma:
       implied-branch-matchers: False

.. attr:: pragma

   The pragma item currently supports the following attributes:

   .. attr:: implied-branch-matchers

      This is a boolean, which, if set, may be used to enable
      (``True``) or disable (``False``) the addition of implied branch
      matchers to job definitions.  Normally Zuul decides whether to
      add these based on heuristics described in :attr:`job.branches`.
      This attribute overrides that behavior.

      This can be useful if a project has multiple branches, yet the
      jobs defined in the master branch should apply to all branches.

      Note that if a job contains an explicit branch matcher, it will
      be used regardless of the value supplied here.

   .. attr:: implied-branches

      This is a list of regular expressions, just as
      :attr:`job.branches`, which may be used to supply the value of
      the implied branch matcher for all jobs in a file.

      This may be useful if two projects share jobs but have
      dissimilar branch names.  If, for example, two projects have
      stable maintenance branches with dissimilar names, but both
      should use the same job variants, this directive may be used to
      indicate that all of the jobs defined in the stable branch of
      the first project may also be used for the stable branch of teh
      other.  For example:

      .. code-block:: yaml

         - pragma:
             implied-branches:
               - stable/foo
               - stable/bar

      The above code, when added to the ``stable/foo`` branch of a
      project would indicate that the job variants described in that
      file should not only be used for changes to ``stable/foo``, but
      also on changes to ``stable/bar``, which may be in another
      project.

      Note that if a job contains an explicit branch matcher, it will
      be used regardless of the value supplied here.

      Note also that the presence of `implied-branches` does not
      automatically set `implied-branch-matchers`.  Zuul will still
      decide if implied branch matchers are warranted at all, using
      the heuristics described in :attr:`job.branches`, and only use
      the value supplied here if that is the case.  If you want to
      declare specific implied branches on, for example, a
      :term:`config-project` project (which normally would not use
      implied branches), you must set `implied-branch-matchers` as
      well.
