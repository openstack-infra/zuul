:title: Zuul

Zuul
====

Configuration
-------------

Zuul has three configuration files:

**zuul.conf**
  Connection information for Gerrit and Gearman, locations of the
  other config files. (required)
**layout.yaml**
  Project and pipeline configuration -- what Zuul does. (required)
**logging.conf**
    Python logging config. (optional)

Examples of each of the three files can be found in the etc/ directory
of the source distribution.

.. _zuulconf:

zuul.conf
~~~~~~~~~

Zuul will look for ``/etc/zuul/zuul.conf`` or ``~/zuul.conf`` to
bootstrap its configuration.  Alternately, you may specify ``-c
/path/to/zuul.conf`` on the command line.

Gerrit and Gearman connection information are each described in a
section of zuul.conf.  The location of the other two configuration
files (as well as the location of the PID file when running Zuul as a
server) are specified in a third section.

The three sections of this config and their options are documented below.
You can also find an example zuul.conf file in the git
`repository
<https://git.openstack.org/cgit/openstack-infra/zuul/tree/etc/zuul.conf-sample>`_

gearman
"""""""

Client connection information for gearman. If using Zuul's builtin gearmand
server just set **server** to 127.0.0.1.

**server**
  Hostname or IP address of the Gearman server.
  ``server=gearman.example.com`` (required)

**port**
  Port on which the Gearman server is listening.
  ``port=4730`` (optional)

gearman_server
""""""""""""""

The builtin gearman server. Zuul can fork a gearman process from itself rather
than connecting to an external one.

**start**
  Whether to start the internal Gearman server (default: False).
  ``start=true``

**listen_address**
  IP address or domain name on which to listen (default: all addresses).
  ``listen_address=127.0.0.1``

**log_config**
  Path to log config file for internal Gearman server.
  ``log_config=/etc/zuul/gearman-logging.yaml``

webapp
""""""

**listen_address**
  IP address or domain name on which to listen (default: 0.0.0.0).
  ``listen_address=127.0.0.1``

**port**
  Port on which the webapp is listening (default: 8001).
  ``port=8008``

zuul
""""

Zuul's main configuration section. At minimum zuul must be able to find
layout.yaml to be useful.

.. note:: Must be provided when running zuul-server

.. _layout_config:

**layout_config**
  Path to layout config file.  Used by zuul-server only.
  ``layout_config=/etc/zuul/layout.yaml``

**log_config**
  Path to log config file.  Used by zuul-server only.
  ``log_config=/etc/zuul/logging.yaml``

**pidfile**
  Path to PID lock file.  Used by zuul-server only.
  ``pidfile=/var/run/zuul/zuul.pid``

**state_dir**
  Path to directory that Zuul should save state to.  Used by all Zuul
  commands.
  ``state_dir=/var/lib/zuul``

**jobroot_dir**
  Path to directory that Zuul should store temporary job files.
  ``jobroot_dir=/tmp``

**report_times**
  Boolean value (``true`` or ``false``) that determines if Zuul should
  include elapsed times for each job in the textual report.  Used by
  zuul-server only.
  ``report_times=true``

**status_url**
  URL that will be posted in Zuul comments made to Gerrit changes when
  starting jobs for a change.  Used by zuul-server only.
  ``status_url=https://zuul.example.com/status``

**status_expiry**
  Zuul will cache the status.json file for this many seconds. This is an
  optional value and ``1`` is used by default.
  ``status_expiry=1``

**job_name_in_report**
  Boolean value (``true`` or ``false``) that indicates whether the
  job name should be included in the report (normally only the URL
  is included).  Defaults to ``false``.  Used by zuul-server only.
  ``job_name_in_report=true``

merger
""""""

The zuul-merger process configuration. Detailed documentation on this process
can be found on the :doc:`merger` page.

.. note:: Must be provided when running zuul-merger. Both services may share the
          same configuration (and even host) or otherwise have an individual
          zuul.conf.

**git_dir**
  Directory that Zuul should clone local git repositories to.
  ``git_dir=/var/lib/zuul/git``

**git_user_email**
  Optional: Value to pass to `git config user.email`.
  ``git_user_email=zuul@example.com``

**git_user_name**
  Optional: Value to pass to `git config user.name`.
  ``git_user_name=zuul``

**zuul_url**
  URL of this merger's git repos, accessible to test workers.  Usually
  "http://zuul.example.com/p" or "http://zuul-merger01.example.com/p"
  depending on whether the merger is co-located with the Zuul server.

**log_config**
  Path to log config file for the merger process.
  ``log_config=/etc/zuul/logging.yaml``

**pidfile**
  Path to PID lock file for the merger process.
  ``pidfile=/var/run/zuul-merger/merger.pid``

executor
""""""""

The zuul-executor process configuration.

**git_dir**
  Directory that Zuul should clone local git repositories to.
  ``git_dir=/var/lib/zuul/git``

**log_config**
  Path to log config file for the executor process.
  ``log_config=/etc/zuul/logging.yaml``

**private_key_file**
  SSH private key file to be used when logging into worker nodes.
  ``private_key_file=~/.ssh/id_rsa``

**user**
  User ID for the zuul-executor process. In normal operation as a daemon,
  the executor should be started as the ``root`` user, but it will drop
  privileges to this user during startup.
  ``user=zuul``

.. _connection:

connection ArbitraryName
""""""""""""""""""""""""

A connection can be listed with any arbitrary name. The required
parameters are specified in the :ref:`connections` documentation
depending on what driver you are using.

.. _layoutyaml:

layout.yaml
~~~~~~~~~~~

This is the main configuration file for Zuul, where all of the pipelines
and projects are defined, what tests should be run, and what actions
Zuul should perform.  There are three sections: pipelines, jobs, and
projects.

Pipelines
"""""""""

Zuul can have any number of independent pipelines.  Whenever a matching
Gerrit event is found for a pipeline, that event is added to the
pipeline, and the jobs specified for that pipeline are run.  When all
jobs specified for the pipeline that were triggered by an event are
completed, Zuul reports back to Gerrit the results.

There are no pre-defined pipelines in Zuul, rather you can define
whatever pipelines you need in the layout file.  This is a very flexible
system that can accommodate many kinds of workflows.

Here is a quick example of a pipeline definition followed by an
explanation of each of the parameters::

  - name: check
    manager: IndependentPipelineManager
    source: my_gerrit
    trigger:
      my_gerrit:
        - event: patchset-created
    success:
      my_gerrit:
        verified: 1
    failure:
      my_gerrit
        verified: -1

**name**
  This is used later in the project definition to indicate what jobs
  should be run for events in the pipeline.

**description**
  This is an optional field that may be used to provide a textual
  description of the pipeline.

**source**
  A required field that specifies a connection that provides access to
  the change objects that this pipeline operates on. The name of the
  connection as per the zuul.conf should be specified. The driver used
  for the connection named will be the source. Currently only ``gerrit``
  drivers are supported.

**success-message**
  An optional field that supplies the introductory text in message
  reported back to Gerrit when all the voting builds are successful.
  Defaults to "Build successful."

**failure-message**
  An optional field that supplies the introductory text in message
  reported back to Gerrit when at least one voting build fails.
  Defaults to "Build failed."

**merge-failure-message**
  An optional field that supplies the introductory text in message
  reported back to Gerrit when a change fails to merge with the
  current state of the repository.
  Defaults to "Merge failed."

**footer-message**
  An optional field to supply additional information after test results.
  Useful for adding information about the CI system such as debugging
  and contact details.

**manager**
  There are currently two schemes for managing pipelines:

  *IndependentPipelineManager*
    Every event in this pipeline should be treated as independent of
    other events in the pipeline.  This is appropriate when the order of
    events in the pipeline doesn't matter because the results of the
    actions this pipeline performs can not affect other events in the
    pipeline.  For example, when a change is first uploaded for review,
    you may want to run tests on that change to provide early feedback
    to reviewers.  At the end of the tests, the change is not going to
    be merged, so it is safe to run these tests in parallel without
    regard to any other changes in the pipeline.  They are independent.

    Another type of pipeline that is independent is a post-merge
    pipeline. In that case, the changes have already merged, so the
    results can not affect any other events in the pipeline.

  *DependentPipelineManager*
    The dependent pipeline manager is designed for gating.  It ensures
    that every change is tested exactly as it is going to be merged
    into the repository.  An ideal gating system would test one change
    at a time, applied to the tip of the repository, and only if that
    change passed tests would it be merged.  Then the next change in
    line would be tested the same way.  In order to achieve parallel
    testing of changes, the dependent pipeline manager performs
    speculative execution on changes.  It orders changes based on
    their entry into the pipeline.  It begins testing all changes in
    parallel, assuming that each change ahead in the pipeline will pass
    its tests.  If they all succeed, all the changes can be tested and
    merged in parallel.  If a change near the front of the pipeline
    fails its tests, each change behind it ignores whatever tests have
    been completed and are tested again without the change in front.
    This way gate tests may run in parallel but still be tested
    correctly, exactly as they will appear in the repository when
    merged.

    One important characteristic of the DependentPipelineManager is that
    it analyzes the jobs that are triggered by different projects, and
    if those projects have jobs in common, it treats those projects as
    related, and they share a single virtual queue of changes.  Thus,
    if there is a job that performs integration testing on two
    projects, those two projects will automatically share a virtual
    change queue.  If a third project does not invoke that job, it
    will be part of a separate virtual change queue, and changes to
    it will not depend on changes to the first two jobs.

    For more detail on the theory and operation of Zuul's
    DependentPipelineManager, see: :doc:`gating`.

**trigger**
  At least one trigger source must be supplied for each pipeline.
  Triggers are not exclusive -- matching events may be placed in
  multiple pipelines, and they will behave independently in each of
  the pipelines they match.

  Triggers are loaded from their connection name. The driver type of
  the connection will dictate which options are available.
  See :doc:`triggers`.

**require**
  If this section is present, it established pre-requisites for any
  kind of item entering the Pipeline.  Regardless of how the item is
  to be enqueued (via any trigger or automatic dependency resolution),
  the conditions specified here must be met or the item will not be
  enqueued.

.. _pipeline-require-approval:

  **approval**
  This requires that a certain kind of approval be present for the
  current patchset of the change (the approval could be added by the
  event in question).  It takes several sub-parameters, all of which
  are optional and are combined together so that there must be an
  approval matching all specified requirements.

    *username*
    If present, an approval from this username is required.  It is
    treated as a regular expression.

    *email*
    If present, an approval with this email address is required.  It
    is treated as a regular expression.

    *email-filter* (deprecated)
    A deprecated alternate spelling of *email*.  Only one of *email* or
    *email_filter* should be used.

    *older-than*
    If present, the approval must be older than this amount of time
    to match.  Provide a time interval as a number with a suffix of
    "w" (weeks), "d" (days), "h" (hours), "m" (minutes), "s"
    (seconds).  Example ``48h`` or ``2d``.

    *newer-than*
    If present, the approval must be newer than this amount of time
    to match.  Same format as "older-than".

    Any other field is interpreted as a review category and value
    pair.  For example ``verified: 1`` would require that the approval
    be for a +1 vote in the "Verified" column.  The value may either
    be a single value or a list: ``verified: [1, 2]`` would match
    either a +1 or +2 vote.

  **open**
  A boolean value (``true`` or ``false``) that indicates whether the change
  must be open or closed in order to be enqueued.

  **current-patchset**
  A boolean value (``true`` or ``false``) that indicates whether the change
  must be the current patchset in order to be enqueued.

  **status**
  A string value that corresponds with the status of the change
  reported by the trigger.  For example, when using the Gerrit
  trigger, status values such as ``NEW`` or ``MERGED`` may be useful.

**reject**
  If this section is present, it establishes pre-requisites that can
  block an item from being enqueued. It can be considered a negative
  version of **require**.

  **approval**
  This takes a list of approvals. If an approval matches the provided
  criteria the change can not be entered into the pipeline. It follows
  the same syntax as the :ref:`"require approval" pipeline above
  <pipeline-require-approval>`.

  Example to reject a change with any negative vote::

    reject:
      approval:
        - code-review: [-1, -2]

**dequeue-on-new-patchset**
  Normally, if a new patchset is uploaded to a change that is in a
  pipeline, the existing entry in the pipeline will be removed (with
  jobs canceled and any dependent changes that can no longer merge as
  well.  To suppress this behavior (and allow jobs to continue
  running), set this to ``false``.  Default: ``true``.

**ignore-dependencies**
  In any kind of pipeline (dependent or independent), Zuul will
  attempt to enqueue all dependencies ahead of the current change so
  that they are tested together (independent pipelines report the
  results of each change regardless of the results of changes ahead).
  To ignore dependencies completely in an independent pipeline, set
  this to ``true``.  This option is ignored by dependent pipelines.
  The default is: ``false``.

**success**
  Describes where Zuul should report to if all the jobs complete
  successfully.
  This section is optional; if it is omitted, Zuul will run jobs and
  do nothing on success; it will not even report a message to Gerrit.
  If the section is present, the listed reporter plugins will be
  asked to report on the jobs.
  The reporters are listed by their connection name. The options
  available depend on the driver for the supplied connection.
  See :doc:`reporters` for more details.

**failure**
  Uses the same syntax as **success**, but describes what Zuul should
  do if at least one job fails.

**merge-failure**
  Uses the same syntax as **success**, but describes what Zuul should
  do if it is unable to merge in the patchset. If no merge-failure
  reporters are listed then the ``failure`` reporters will be used to
  notify of unsuccessful merges.

**start**
  Uses the same syntax as **success**, but describes what Zuul should
  do when a change is added to the pipeline manager.  This can be used,
  for example, to reset the value of the Verified review category.

**disabled**
  Uses the same syntax as **success**, but describes what Zuul should
  do when a pipeline is disabled.
  See ``disable-after-consecutive-failures``.

**disable-after-consecutive-failures**
  If set, a pipeline can enter a ''disabled'' state if too many changes
  in a row fail. When this value is exceeded the pipeline will stop
  reporting to any of the ``success``, ``failure`` or ``merge-failure``
  reporters and instead only report to the ``disabled`` reporters.
  (No ``start`` reports are made when a pipeline is disabled).

**precedence**
  Indicates how the build scheduler should prioritize jobs for
  different pipelines.  Each pipeline may have one precedence, jobs
  for pipelines with a higher precedence will be run before ones with
  lower.  The value should be one of ``high``, ``normal``, or ``low``.
  Default: ``normal``.

**window**
  DependentPipelineManagers only. Zuul can rate limit
  DependentPipelineManagers in a manner similar to TCP flow control.
  Jobs are only started for changes in the queue if they sit in the
  actionable window for the pipeline. The initial length of this window
  is configurable with this value. The value given should be a positive
  integer value. A value of ``0`` disables rate limiting on the
  DependentPipelineManager.
  Default: ``20``.

**window-floor**
  DependentPipelineManagers only. This is the minimum value for the
  window described above. Should be a positive non zero integer value.
  Default: ``3``.

**window-increase-type**
  DependentPipelineManagers only. This value describes how the window
  should grow when changes are successfully merged by zuul. A value of
  ``linear`` indicates that ``window-increase-factor`` should be added
  to the previous window value. A value of ``exponential`` indicates
  that ``window-increase-factor`` should be multiplied against the
  previous window value and the result will become the window size.
  Default: ``linear``.

**window-increase-factor**
  DependentPipelineManagers only. The value to be added or multiplied
  against the previous window value to determine the new window after
  successful change merges.
  Default: ``1``.

**window-decrease-type**
  DependentPipelineManagers only. This value describes how the window
  should shrink when changes are not able to be merged by Zuul. A value
  of ``linear`` indicates that ``window-decrease-factor`` should be
  subtracted from the previous window value. A value of ``exponential``
  indicates that ``window-decrease-factor`` should be divided against
  the previous window value and the result will become the window size.
  Default: ``exponential``.

**window-decrease-factor**
  DependentPipelineManagers only. The value to be subtracted or divided
  against the previous window value to determine the new window after
  unsuccessful change merges.
  Default: ``2``.

Some example pipeline configurations are included in the sample layout
file.  The first is called a *check* pipeline::

  - name: check
    manager: IndependentPipelineManager
    trigger:
      my_gerrit:
        - event: patchset-created
    success:
      my_gerrit:
        verified: 1
    failure:
      my_gerrit:
        verified: -1

This will trigger jobs each time a new patchset (or change) is
uploaded to Gerrit, and report +/-1 values to Gerrit in the
``verified`` review category. ::

  - name: gate
    manager: DependentPipelineManager
    trigger:
      my_gerrit:
        - event: comment-added
          approval:
            - approved: 1
    success:
      my_gerrit:
        verified: 2
        submit: true
    failure:
      my_gerrit:
        verified: -2

This will trigger jobs whenever a reviewer leaves a vote of ``1`` in the
``approved`` review category in Gerrit (a non-standard category).
Changes will be tested in such a way as to guarantee that they will be
merged exactly as tested, though that will happen in parallel by
creating a virtual queue of dependent changes and performing
speculative execution of jobs. ::

  - name: post
    manager: IndependentPipelineManager
    trigger:
      my_gerrit:
        - event: ref-updated
          ref: ^(?!refs/).*$

This will trigger jobs whenever a change is merged to a named branch
(e.g., ``master``).  No output will be reported to Gerrit.  This is
useful for side effects such as creating per-commit tarballs. ::

  - name: silent
    manager: IndependentPipelineManager
    trigger:
      my_gerrit:
        - event: patchset-created

This also triggers jobs when changes are uploaded to Gerrit, but no
results are reported to Gerrit.  This is useful for jobs that are in
development and not yet ready to be presented to developers. ::

  pipelines:
    - name: post-merge
      manager: IndependentPipelineManager
      trigger:
        my_gerrit:
          - event: change-merged
      success:
        my_gerrit:
          force-message: True
      failure:
        my_gerrit:
          force-message: True

The ``change-merged`` events happen when a change has been merged in the git
repository. The change is thus closed and Gerrit will not accept modifications
to the review scoring such as ``code-review`` or ``verified``. By using the
``force-message: True`` parameter, Zuul will pass ``--force-message`` to the
``gerrit review`` command, thus making sure the message is actually
sent back to Gerrit regardless of approval scores.
That kind of pipeline is nice to run regression or performance tests.

.. note::
  The ``change-merged`` event does not include the commit sha1 which can be
  hazardous, it would let you report back to Gerrit though.  If you were to
  build a tarball for a specific commit, you should consider instead using
  the ``ref-updated`` event which does include the commit sha1 (but lacks the
  Gerrit change number).


.. _jobs:

Jobs
""""

The jobs section is optional, and can be used to set attributes of
jobs that are independent of their association with a project.  For
example, if a job should return a customized message on failure, that
may be specified here.  Otherwise, Zuul does not need to be told about
each job as it builds a list from the project specification.

**name**
  The name of the job.  This field is treated as a regular expression
  and will be applied to each job that matches.

**queue-name (optional)**
  Zuul will automatically combine projects that share a job into
  shared change queues for dependent pipeline managers.  In order to
  report statistics about these queues, it is convenient for them to
  have names.  Zuul can automatically name change queues, however
  these can grow quite long and are prone to changing as projects in
  the queue change.  If you assign a queue-name to a job, Zuul will
  use that as the name for the shared change queue that contains that
  job instead of the automatically generated one.  It is an error for
  a shared change queue to have more than one job with a queue-name if
  they are not the same.

**failure-message (optional)**
  The message that should be reported to Gerrit if the job fails.

**success-message (optional)**
  The message that should be reported to Gerrit if the job fails.

**failure-pattern (optional)**
  The URL that should be reported to Gerrit if the job fails.
  Defaults to the build URL or the url_pattern configured in
  zuul.conf.  May be supplied as a string pattern with substitutions
  as described in url_pattern in :ref:`zuulconf`.

**success-pattern (optional)**
  The URL that should be reported to Gerrit if the job succeeds.
  Defaults to the build URL or the url_pattern configured in
  zuul.conf.  May be supplied as a string pattern with substitutions
  as described in url_pattern in :ref:`zuulconf`.

**hold-following-changes (optional)**
  This is a boolean that indicates that changes that follow this
  change in a dependent change pipeline should wait until this job
  succeeds before executing.  If this is applied to a very short job
  that can predict whether longer jobs will fail early, this can be
  used to reduce the number of jobs that Zuul will execute and
  ultimately have to cancel.  In that case, a small amount of
  parallelization of jobs is traded for more efficient use of testing
  resources.  On the other hand, to apply this to a long running job
  would largely defeat the parallelization of dependent change testing
  that is the main feature of Zuul.  Default: ``false``.

**semaphore (optional)**
  This is a string that names a semaphore that should be observed by this
  job.  The semaphore defines how many jobs which reference that semaphore
  can be enqueued at a time.  This applies across all pipelines in the same
  tenant.  The max value of the semaphore can be specified in the config
  repositories and defaults to 1.

**branch (optional)**
  This job should only be run on matching branches.  This field is
  treated as a regular expression and multiple branches may be
  listed.

**files (optional)**
  This job should only be run if at least one of the files involved in
  the change (added, deleted, or modified) matches at least one of the
  file patterns listed here.  This field is treated as a regular
  expression and multiple expressions may be listed.

**skip-if (optional)**

  This job should not be run if all the patterns specified by the
  optional fields listed below match on their targets.  When multiple
  sets of parameters are provided, this job will be skipped if any set
  matches.  For example: ::

    jobs:
      - name: check-tempest-dsvm-neutron
        skip-if:
          - project: ^openstack/neutron$
            branch: ^stable/juno$
            all-files-match-any:
              - ^neutron/tests/.*$
              - ^tools/.*$
          - all-files-match-any:
              - ^doc/.*$
              - ^.*\.rst$

  With this configuration, the job would be skipped for a neutron
  patchset for the stable/juno branch provided that every file in the
  change matched at least one of the specified file regexes.  The job
  will also be skipped for any patchset that modified only the doc
  tree or rst files.

  *project* (optional)
    The regular expression to match against the project of the change.

  *branch* (optional)
    The regular expression to match against the branch or ref of the
    change.

  *all-files-match-any* (optional)
    A list of regular expressions intended to match the files involved
    in the change.  This parameter will be considered matching a
    change only if all files in a change match at least one of these
    expressions.

    The pattern for '/COMMIT_MSG' is always matched on and does not
    have to be included. Exception is merge commits (without modified
    files), in this case '/COMMIT_MSG' is not matched, and job is not
    skipped. In case of merge commits it's assumed that list of modified
    files isn't predictible and CI should be run.

**voting (optional)**
  Boolean value (``true`` or ``false``) that indicates whatever
  a job is voting or not.  Default: ``true``.

**attempts (optional)**
  Number of attempts zuul will execute a job. Once reached, zuul will report
  RETRY_LIMIT as the job result.
  Defaults to 3.

**tags (optional)**
  A list of arbitrary strings which will be associated with the job.

Here is an example of setting the failure message for jobs that check
whether a change merges cleanly::

  - name: ^.*-merge$
    failure-message: This change or one of its cross-repo dependencies
    was unable to be automatically merged with the current state of
    its repository. Please rebase the change and upload a new
    patchset.

Projects
""""""""

The projects section indicates what jobs should be run in each pipeline
for events associated with each project.  It contains a list of
projects.  Here is an example::

  - name: example/project
    check:
      - project-merge:
        - project-unittest
        - project-pep8
        - project-pyflakes
    gate:
      - project-merge:
        - project-unittest
        - project-pep8
        - project-pyflakes
    post:
      - project-publish

**name**
  The name of the project (as known by Gerrit).

**merge-mode (optional)**
  An optional value that indicates what strategy should be used to
  merge changes to this project.  Supported values are:

  ** merge-resolve **
  Equivalent to 'git merge -s resolve'.  This corresponds closely to
  what Gerrit performs (using JGit) for a project if the "Merge if
  necessary" merge mode is selected and "Automatically resolve
  conflicts" is checked.  This is the default.

  ** merge **
  Equivalent to 'git merge'.

  ** cherry-pick **
  Equivalent to 'git cherry-pick'.

This is followed by a section for each of the pipelines defined above.
Pipelines may be omitted if no jobs should run for this project in a
given pipeline.  Within the pipeline section, the jobs that should be
executed are listed.  If a job is entered as a dictionary key, then
jobs contained within that key are only executed if the key job
succeeds.  In the above example, project-unittest, project-pep8, and
project-pyflakes are only executed if project-merge succeeds.
Furthermore, project-finaltest is executed only if project-unittest,
project-pep8 and project-pyflakes all succeed. This can help avoid
running unnecessary jobs while maximizing parallelism. It is also
useful when distributing results between jobs.

The special job named ``noop`` is internal to Zuul and will always
return ``SUCCESS`` immediately.  This can be useful if you require
that all changes be processed by a pipeline but a project has no jobs
that can be run on it.

.. seealso:: The OpenStack Zuul configuration for a comprehensive example: https://git.openstack.org/cgit/openstack-infra/project-config/tree/zuul/layout.yaml

Project Templates
"""""""""""""""""

Whenever you have lot of similar projects (such as plugins for a project) you
will most probably want to use the same pipeline configurations.  The
project templates let you define pipelines and job name templates to trigger.
One can then just apply the template on its project which make it easier to
update several similar projects. As an example::

  project-templates:
    # Name of the template
    - name: plugin-triggering
      # Definition of pipelines just like for a `project`
      check:
       - '{jobprefix}-merge':
         - '{jobprefix}-pep8'
         - '{jobprefix}-pyflakes'
      gate:
       - '{jobprefix}-merge':
         - '{jobprefix}-unittest'
         - '{jobprefix}-pep8'
         - '{jobprefix}-pyflakes'

In your projects definition, you will then apply the template using the template
key::

  projects:
   - name: plugin/foobar
     template:
      - name: plugin-triggering
        jobprefix: plugin-foobar

You can pass several parameters to a template. A ``parameter`` value
will be used for expansion of ``{parameter}`` in the template
strings. The parameter ``name`` will be automatically provided and
will contain the short name of the project, that is the portion of the
project name after the last ``/`` character.

Multiple templates can be combined in a project, and the jobs from all
of those templates will be added to the project.  Individual jobs may
also be added::

  projects:
   - name: plugin/foobar
     template:
      - name: plugin-triggering
        jobprefix: plugin-foobar
      - name: plugin-extras
        jobprefix: plugin-foobar
     check:
      - foobar-extra-special-job

Individual jobs may optionally be added to pipelines (e.g. check,
gate, et cetera) for a project, in addition to those provided by
templates.

The order of the jobs listed in the project (which only affects the
order of jobs listed on the report) will be the jobs from each
template in the order listed, followed by any jobs individually listed
for the project.

Note that if multiple templates are used for a project and one
template specifies a job that is also specified in another template,
or specified in the project itself, the configuration defined by
either the last template or the project itself will take priority.


Semaphores
""""""""""

When using semaphores the maximum value of each one can be specified in their
respective config repositories.  Unspecified semaphores default to 1::

  - semaphore:
      name: semaphore-foo
      max: 5
  - semaphore:
      name: semaphore-bar
      max: 3


logging.conf
~~~~~~~~~~~~
This file is optional.  If provided, it should be a standard
:mod:`logging.config` module configuration file.  If not present, Zuul will
output all log messages of DEBUG level or higher to the console.

Starting Zuul
-------------

To start Zuul, run **zuul-server**::

  usage: zuul-server [-h] [-c CONFIG] [-l LAYOUT] [-d] [-t] [--version]

  Project gating system.

  optional arguments:
    -h, --help  show this help message and exit
    -c CONFIG   specify the config file
    -l LAYOUT   specify the layout file
    -d          do not run as a daemon
    -t          validate layout file syntax
    --version   show zuul version

You may want to use the ``-d`` argument while you are initially setting
up Zuul so you can detect any configuration errors quickly.  Under
normal operation, omit ``-d`` and let Zuul run as a daemon.

If you send signal 1 (SIGHUP) to the zuul-server process, Zuul will
stop executing new jobs, wait until all executing jobs are finished,
reload its layout.yaml, and resume. Changes to any connections or
the PID  file will be ignored until Zuul is restarted.

If you send a SIGUSR1 to the zuul-server process, Zuul will stop
executing new jobs, wait until all executing jobs are finished,
then exit. While waiting to exit Zuul will queue Gerrit events and
save these events prior to exiting. When Zuul starts again it will
read these saved events and act on them.

If you need to abort Zuul and intend to manually requeue changes for
jobs which were running in its pipelines, prior to terminating you can
use the zuul-changes.py tool script to simplify the process. For
example, this would give you a list of zuul-enqueue commands to requeue
changes for the gate and check pipelines respectively::

  ./tools/zuul-changes.py http://zuul.openstack.org/ gate
  ./tools/zuul-changes.py http://zuul.openstack.org/ check

If you send a SIGUSR2 to the zuul-server process, or the forked process
that runs the Gearman daemon, Zuul will dump a stack trace for each
running thread into its debug log. It is written under the log bucket
``zuul.stack_dump``.  This is useful for tracking down deadlock or
otherwise slow threads.

When `yappi <https://code.google.com/p/yappi/>`_ (Yet Another Python
Profiler) is available, additional functions' and threads' stats are
emitted as well. The first SIGUSR2 will enable yappi, on the second
SIGUSR2 it dumps the information collected, resets all yappi state and
stops profiling. This is to minimize the impact of yappi on a running
system.
