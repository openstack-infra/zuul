:title: Zuul

Zuul
====

Configuration
-------------

Zuul has three configuration files:

**zuul.conf**
  Connection information for Gerrit and Gearman, locations of the
  other config files
**layout.yaml**
  Project and pipeline configuration -- what Zuul does
**logging.conf**
    Python logging config

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
<https://github.com/openstack-infra/zuul/blob/master/etc/zuul.conf-sample>`_

gearman
"""""""

**server**
  Hostname or IP address of the Gearman server.
  ``server=gearman.example.com``

**port**
  Port on which the Gearman server is listening
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

**layout_config**
  Path to layout config file.
  ``layout_config=/etc/zuul/layout.yaml``

**log_config**
  Path to log config file.
  ``log_config=/etc/zuul/logging.yaml``

**pidfile**
  Path to PID lock file.
  ``pidfile=/var/run/zuul/zuul.pid``

**state_dir**
  Path to directory that Zuul should save state to.
  ``state_dir=/var/lib/zuul``

**git_dir**
  Directory that Zuul should clone local git repositories to.
  ``git_dir=/var/lib/zuul/git``

**git_user_email**
  Optional: Value to pass to `git config user.email`.
  ``git_user_email=zuul@example.com``

**git_user_name**
  Optional: Value to pass to `git config user.name`.
  ``git_user_name=zuul``

**push_change_refs**
  Boolean value (``true`` or ``false``) that determines if Zuul should
  push change refs to the git origin server for the git repositories in
  git_dir.
  ``push_change_refs=true``

**report_times**
  Boolean value (``true`` or ``false``) that determines if Zuul should
  include elapsed times for each job in the textual report.
  ``report_times=true``

**status_url**
  URL that will be posted in Zuul comments made to Gerrit changes when
  starting jobs for a change.
  ``status_url=https://zuul.example.com/status``

**url_pattern**
  If you are storing build logs external to the system that originally
  ran jobs and wish to link to those logs when Zuul makes comments on
  Gerrit changes for completed jobs this setting configures what the
  URLs for those links should be.
  ``http://logs.example.com/{change.number}/{change.patchset}/{pipeline.name}/{job.name}/{build.number}``

**job_name_in_report**
  Boolean value (``true`` or ``false``) that indicates whether the
  job name should be included in the report (normally only the URL
  is included).  Defaults to ``false``.
  ``job_name_in_report=true``

**zuul_url**
  URL of Zuul's git repos, accessible to test workers.  
  Usually "http://zuul.example.com/p".

smtp
""""

**server**
  SMTP server hostname or address to use.
  ``server=localhost``

**default_from**
  Who the email should appear to be sent from when emailing the report.
  This can be overridden by individual pipelines.
  ``default_from=zuul@example.com``

**default_to**
  Who the report should be emailed to by default.
  This can be overridden by individual pipelines.
  ``default_to=you@example.com``

replication
"""""""""""

Zuul can push the refs it creates to any number of servers.  To do so,
list the git push URLs in this section, one per line as follows::

  [replication]
    url1=ssh://user@host1.example.com:port/path/to/repo
    url2=ssh://user@host2.example.com:port/path/to/repo

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
  The path to a python file.  The file will be loaded and objects that
  it defines will be placed in a special environment which can be
  referenced in the Zuul configuration.  Currently only the
  parameter-function attribute of a Job uses this feature.

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

**success-message**
  An optional field that supplies the introductory text in message
  reported back to Gerrit when all the voting builds are successful.
  Defaults to "Build successful."

**failure-message**
  An optional field that supplies the introductory text in message
  reported back to Gerrit when at least one voting build fails.
  Defaults to "Build failed."

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
  Exactly one trigger source must be supplied for each pipeline.
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

    *email_filter*
    This is used for any event.  It takes a regex applied on the performer
    email, i.e. Gerrit account email address.  If you want to specify
    several email filters, you must use a YAML list.  Make sure to use non
    greedy matchers and to escapes dots!
    Example: ``email_filter: ^.*?@example\.org$``.

    *comment_filter*
    This is only used for ``comment-added`` events.  It accepts a list of
    regexes that are searched for in the comment string. If any of these
    regexes matches a portion of the comment string the trigger is
    matched. ``comment_filter: retrigger`` will match when comments
    containing 'retrigger' somewhere in the comment text are added to a
    change.

  **timer**
    This trigger will run based on a cron-style time specification.
    It will enqueue an event into its pipeline for every project
    defined in the configuration.  Any job associated with the
    pipeline will run in response to that event.

    *time*
    The time specification in cron syntax.  Only the 5 part syntax is
    supported, not the symbolic names.  Example: ``0 0 * * *`` runs
    at midnight.


**dequeue-on-new-patchset**
  Normally, if a new patchset is uploaded to a change that is in a
  pipeline, the existing entry in the pipeline will be removed (with
  jobs canceled and any dependent changes that can no longer merge as
  well.  To suppress this behavior (and allow jobs to continue
  running), set this to ``false``.  Default: ``true``.

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
  the ``ref-updated`` event which does include the commit sha1 (but lack the
  Gerrit change number).

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

.. seealso:: The OpenStack Zuul configuration for a comprehensive example: https://github.com/openstack-infra/config/blob/master/modules/openstack_project/files/zuul/layout.yaml

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

The order of the jobs listed in the project (which only affects the
order of jobs listed on the report) will be the jobs from each
template in the order listed, followed by any jobs individually listed
for the project.

Note that if multiple templates are used for a project and one
template specifies a job that is also specified in another template,
or specified in the project itself, those jobs will be duplicated in
the resulting project configuration.

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
      http://zuul.openstack.org/ gate 'reverify no bug'
  ./tools/zuul-changes.py --review-host=review.openstack.org \
      http://zuul.openstack.org/ check 'recheck no bug'

If you send a SIGUSR2 to the zuul-server process, Zuul will dump a stack
trace for each running thread into its debug log. This is useful for
tracking down deadlock or otherwise slow threads.
