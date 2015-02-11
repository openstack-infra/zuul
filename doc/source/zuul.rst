:title: Zuul

Zuul
====

Configuration
-------------

Zuul has three configuration files:

**zuul.conf**
  Connection information for Gerrit and Gearman, locations of the
  other config files.
**layout.yaml**
  Project and pipeline configuration -- what Zuul does.
**logging.conf**
    Python logging config.

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

**server**
  Hostname or IP address of the Gearman server.
  ``server=gearman.example.com``

**port**
  Port on which the Gearman server is listening.
  ``port=4730``

gearman_server
""""""""""""""

**start**
  Whether to start the internal Gearman server (default: False).
  ``start=true``

**log_config**
  Path to log config file for internal Gearman server.
  ``log_config=/etc/zuul/gearman-logging.yaml``

gerrit
""""""

**server**
  FQDN of Gerrit server.
  ``server=review.example.com``

**port**
  Optional: Gerrit server port.
  ``port=29418``

**baseurl**
  Optional: path to Gerrit web interface. Defaults to ``https://<value
  of server>/``. ``baseurl=https://review.example.com/review_site/``

**user**
  User name to use when logging into above server via ssh.
  ``user=zuul``

**sshkey**
  Path to SSH key to use when logging into above server.
  ``sshkey=/home/zuul/.ssh/id_rsa``

zuul
""""

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

**url_pattern**
  If you are storing build logs external to the system that originally
  ran jobs and wish to link to those logs when Zuul makes comments on
  Gerrit changes for completed jobs this setting configures what the
  URLs for those links should be.  Used by zuul-server only.
  ``http://logs.example.com/{change.number}/{change.patchset}/{pipeline.name}/{job.name}/{build.number}``

**job_name_in_report**
  Boolean value (``true`` or ``false``) that indicates whether the
  job name should be included in the report (normally only the URL
  is included).  Defaults to ``false``.  Used by zuul-server only.
  ``job_name_in_report=true``

merger
""""""

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

smtp
""""

**server**
  SMTP server hostname or address to use.
  ``server=localhost``

**port**
  Optional: SMTP server port.
  ``port=25``

**default_from**
  Who the email should appear to be sent from when emailing the report.
  This can be overridden by individual pipelines.
  ``default_from=zuul@example.com``

**default_to**
  Who the report should be emailed to by default.
  This can be overridden by individual pipelines.
  ``default_to=you@example.com``

.. _swift:

swift
"""""

To send (optional) swift upload instructions this section must be
present. Multiple destinations can be defined in the :ref:`jobs` section
of the layout.

If you are sending the temp-url-key or fetching the x-storage-url, you
will need the python-swiftclient module installed.

**X-Account-Meta-Temp-Url-Key** (optional)
  This is the key used to sign the HMAC message. If you do not set a
  key Zuul will generate one automatically.

**Send-Temp-Url-Key** (optional)
  Zuul can send the X-Account-Meta-Temp-Url-Key to swift for you if
  you have set up the appropriate credentials in ``authurl`` below.
  This isn't necessary if you know and have set your
  X-Account-Meta-Temp-Url-Key.
  If set, Zuul requires the python-swiftclient module.
  ``default: true``

**X-Storage-Url** (optional)
  The storage URL is the destination to upload files into. If you do
  not set this the ``authurl`` credentials are used to fetch the url
  from swift and Zuul will requires the python-swiftclient module.

**authurl** (optional)
  The (keystone) Auth URL for swift.
  ``For example, https://identity.api.rackspacecloud.com/v2.0/``
  This is required if you have Send-Temp-Url-Key set to ``True`` or
  if you have not supplied the X-Storage-Url.

Any of the `swiftclient connection parameters`_ can also be defined
here by the same name. Including the os_options by their key name (
``for example tenant_id``)

.. _swiftclient connection parameters: http://docs.openstack.org/developer/python-swiftclient/swiftclient.html#module-swiftclient.client

**region_name** (optional)
  The region name holding the swift container
  ``For example, SYD``

Each destination defined by the :ref:`jobs` will have the following
default values that it may overwrite.

**default_container** (optional)
  Container name to place the log into
  ``For example, logs``

**default_expiry** (optional)
  How long the signed destination should be available for
  ``default: 7200 (2hrs)``

**default_max_file_size** (optional)
  The maximum size of an individual file
  ``default: 104857600 (100MB)``

**default_max_file_count** (optional)
  The maximum number of separate files to allow
  ``default: 10``

**default_logserver_prefix**
  Provide a URL to the CDN or logserver app so that a worker knows
  what URL to return. The worker should return the logserver_prefix
  url and the object path.
  ``For example: http://logs.example.org/server.app?obj=``

layout.yaml
~~~~~~~~~~~

This is the main configuration file for Zuul, where all of the pipelines
and projects are defined, what tests should be run, and what actions
Zuul should perform.  There are three sections: pipelines, jobs, and
projects.

.. _includes:

Includes
""""""""

Custom functions to be used in Zuul's configuration may be provided
using the ``includes`` directive.  It accepts a list of files to
include, and currently supports one type of inclusion, a python file::

  includes:
    - python-file: local_functions.py

**python-file**
  The path to a python file (either an absolute path or relative to the
  directory name of :ref:`layout_config <layout_config>`).  The
  file will be loaded and objects that it defines will be placed in a
  special environment which can be referenced in the Zuul configuration.
  Currently only the parameter-function attribute of a Job uses this
  feature.

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
    source: gerrit
    trigger:
      gerrit:
        - event: patchset-created
    success:
      verified: 1
    failure:
      verified: -1

**name**
  This is used later in the project definition to indicate what jobs
  should be run for events in the pipeline.

**description**
  This is an optional field that may be used to provide a textual
  description of the pipeline.

**source**
  A required field that specifies a trigger that provides access to
  the change objects that this pipeline operates on.  Currently only
  the value ``gerrit`` is supported.

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
  the pipelines they match.  You may select from the following:

  **gerrit**
    This describes what Gerrit events should be placed in the
    pipeline.  Multiple gerrit triggers may be listed.  Further
    parameters describe the kind of events that match:

    *event*
    The event name from gerrit.  Examples: ``patchset-created``,
    ``comment-added``, ``ref-updated``.  This field is treated as a
    regular expression.

    *branch*
    The branch associated with the event.  Example: ``master``.  This
    field is treated as a regular expression, and multiple branches may
    be listed.

    *ref*
    On ref-updated events, the branch parameter is not used, instead the
    ref is provided.  Currently Gerrit has the somewhat idiosyncratic
    behavior of specifying bare refs for branch names (e.g., ``master``),
    but full ref names for other kinds of refs (e.g., ``refs/tags/foo``).
    Zuul matches what you put here exactly against what Gerrit
    provides.  This field is treated as a regular expression, and
    multiple refs may be listed.

    *approval*
    This is only used for ``comment-added`` events.  It only matches if
    the event has a matching approval associated with it.  Example:
    ``code-review: 2`` matches a ``+2`` vote on the code review category.
    Multiple approvals may be listed.

    *email*
    This is used for any event.  It takes a regex applied on the performer
    email, i.e. Gerrit account email address.  If you want to specify
    several email filters, you must use a YAML list.  Make sure to use non
    greedy matchers and to escapes dots!
    Example: ``email: ^.*?@example\.org$``.

    *email_filter* (deprecated)
    A deprecated alternate spelling of *email*.  Only one of *email* or
    *email_filter* should be used.

    *username*
    This is used for any event.  It takes a regex applied on the performer
    username, i.e. Gerrit account name.  If you want to specify several
    username filters, you must use a YAML list.  Make sure to use non greedy
    matchers and to escapes dots!
    Example: ``username: ^jenkins$``.

    *username_filter* (deprecated)
    A deprecated alternate spelling of *username*.  Only one of *username* or
    *username_filter* should be used.

    *comment*
    This is only used for ``comment-added`` events.  It accepts a list of
    regexes that are searched for in the comment string. If any of these
    regexes matches a portion of the comment string the trigger is
    matched. ``comment: retrigger`` will match when comments
    containing 'retrigger' somewhere in the comment text are added to a
    change.

    *comment_filter* (deprecated)
    A deprecated alternate spelling of *comment*.  Only one of *comment* or
    *comment_filter* should be used.

    *require-approval*
    This may be used for any event.  It requires that a certain kind
    of approval be present for the current patchset of the change (the
    approval could be added by the event in question).  It follows the
    same syntax as the :ref:`"approval" pipeline requirement below
    <pipeline-require-approval>`.

  **timer**
    This trigger will run based on a cron-style time specification.
    It will enqueue an event into its pipeline for every project
    defined in the configuration.  Any job associated with the
    pipeline will run in response to that event.

    *time*
    The time specification in cron syntax.  Only the 5 part syntax is
    supported, not the symbolic names.  Example: ``0 0 * * *`` runs
    at midnight.

  **zuul**
    This trigger supplies events generated internally by Zuul.
    Multiple events may be listed.

    *event*
    The event name.  Currently supported:

      *project-change-merged* when Zuul merges a change to a project,
      it generates this event for every open change in the project.

      *parent-change-enqueued* when Zuul enqueues a change into any
      pipeline, it generates this event for every child of that
      change.

    *pipeline*
    Only available for ``parent-change-enqueued`` events.  This is the
    name of the pipeline in which the parent change was enqueued.

    *require-approval*
    This may be used for any event.  It requires that a certain kind
    of approval be present for the current patchset of the change (the
    approval could be added by the event in question).  It follows the
    same syntax as the :ref:`"approval" pipeline requirement below
    <pipeline-require-approval>`.


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
    If present, an approval from this username is required.

    *email*
    If present, an approval with this email address is required.  It
    is treated as a regular expression as above.

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
  Each reporter's value dictionary is handled by the reporter. See
  reporters for more details.

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
  DependentPipelineManagers only. The value to be added or mulitplied
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
      - event: patchset-created
    success:
      gerrit:
        verified: 1
    failure:
      gerrit:
        verified: -1

This will trigger jobs each time a new patchset (or change) is
uploaded to Gerrit, and report +/-1 values to Gerrit in the
``verified`` review category. ::

  - name: gate
    manager: DependentPipelineManager
    trigger:
      - event: comment-added
        approval:
          - approved: 1
    success:
      gerrit:
        verified: 2
        submit: true
    failure:
      gerrit:
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
      - event: ref-updated
        ref: ^(?!refs/).*$

This will trigger jobs whenever a change is merged to a named branch
(e.g., ``master``).  No output will be reported to Gerrit.  This is
useful for side effects such as creating per-commit tarballs. ::

  - name: silent
    manager: IndependentPipelineManager
    trigger:
      - event: patchset-created

This also triggers jobs when changes are uploaded to Gerrit, but no
results are reported to Gerrit.  This is useful for jobs that are in
development and not yet ready to be presented to developers. ::

  pipelines:
    - name: post-merge
      manager: IndependentPipelineManager
      trigger:
        - event: change-merged
      success:
        gerrit:
          force-message: True
      failure:
        gerrit:
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
  succeeds before launching.  If this is applied to a very short job
  that can predict whether longer jobs will fail early, this can be
  used to reduce the number of jobs that Zuul will launch and
  ultimately have to cancel.  In that case, a small amount of
  parallelization of jobs is traded for more efficient use of testing
  resources.  On the other hand, to apply this to a long running job
  would largely defeat the parallelization of dependent change testing
  that is the main feature of Zuul.  Default: ``false``.

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
    have to be included.

**voting (optional)**
  Boolean value (``true`` or ``false``) that indicates whatever
  a job is voting or not.  Default: ``true``.

**parameter-function (optional)**
  Specifies a function that should be applied to the parameters before
  the job is launched.  The function should be defined in a python file
  included with the :ref:`includes` directive.  The function
  should have the following signature:

  .. function:: parameters(item, job, parameters)

     Manipulate the parameters passed to a job before a build is
     launched.  The ``parameters`` dictionary will already contain the
     standard Zuul job parameters, and is expected to be modified
     in-place.

     :param item: the current queue item
     :type item: zuul.model.QueueItem
     :param job: the job about to be run
     :type job: zuul.model.Job
     :param parameters: parameters to be passed to the job
     :type parameters: dict

  If the parameter **ZUUL_NODE** is set by this function, then it will
  be used to specify on what node (or class of node) the job should be
  run.

**swift**
  If :ref:`swift` is configured then each job can define a destination
  container for the builder to place logs and/or assets into. Multiple
  containers can be listed for each job by providing a unique ``name``.

  *name*
    Set an identifying name for the container. This is used in the
    parameter key sent to the builder. For example if it ``logs`` then
    one of the parameters sent will be ``SWIFT_logs_CONTAINER``
    (case-sensitive).

  Each of the defaults defined in :ref:`swift` can be overwritten as:

  *container* (optional)
    Container name to place the log into
    ``For example, logs``

  *expiry* (optional)
    How long the signed destination should be available for

  *max-file-size** (optional)
    The maximum size of an individual file

  *max_file_size** (optional, deprecated)
    A deprecated alternate spelling of *max-file-size*.

  *max-file-count* (optional)
    The maximum number of separate files to allow

  *max_file_count* (optional, deprecated)
    A deprecated alternate spelling of *max-file-count*.

  *logserver-prefix*
    Provide a URL to the CDN or logserver app so that a worker knows
    what URL to return.
    ``For example: http://logs.example.org/server.app?obj=``
    The worker should return the logserver-prefix url and the object
    path as the URL in the results data packet.

  *logserver_prefix* (deprecated)
    A deprecated alternate spelling of *logserver-prefix*.

Here is an example of setting the failure message for jobs that check
whether a change merges cleanly::

  - name: ^.*-merge$
    failure-message: This change was unable to be automatically merged
    with the current state of the repository. Please rebase your
    change and upload a new patchset.

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
project-pyflakes are only executed if project-merge succeeds.  This
can help avoid running unnecessary jobs.

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
gate, et cetera) for a project, in addtion to those provided by
templates.

The order of the jobs listed in the project (which only affects the
order of jobs listed on the report) will be the jobs from each
template in the order listed, followed by any jobs individually listed
for the project.

Note that if multiple templates are used for a project and one
template specifies a job that is also specified in another template,
or specified in the project itself, the configuration defined by
either the last template or the project itself will take priority.

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
reload its configuration, and resume.  Any values in any of the
configuration files may be changed, except the location of Zuul's PID
file (a change to that will be ignored until Zuul is restarted).

If you send a SIGUSR1 to the zuul-server process, Zuul will stop
executing new jobs, wait until all executing jobs are finished,
then exit. While waiting to exit Zuul will queue Gerrit events and
save these events prior to exiting. When Zuul starts again it will
read these saved events and act on them.

If you need to abort Zuul and intend to manually requeue changes for
jobs which were running in its pipelines, prior to terminating you can
use the zuul-changes.py tool script to simplify the process. For
example, this would give you a list of Gerrit commands to reverify or
recheck changes for the gate and check pipelines respectively::

  ./tools/zuul-changes.py --review-host=review.openstack.org \
      http://zuul.openstack.org/ gate 'reverify'
  ./tools/zuul-changes.py --review-host=review.openstack.org \
      http://zuul.openstack.org/ check 'recheck'

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
