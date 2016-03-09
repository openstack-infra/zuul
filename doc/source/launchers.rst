:title: Launchers

.. _Gearman: http://gearman.org/

.. _`Gearman Plugin`:
   https://wiki.jenkins-ci.org/display/JENKINS/Gearman+Plugin

.. _`Turbo-Hipster`:
   http://git.openstack.org/cgit/stackforge/turbo-hipster/

.. _`Turbo-Hipster Documentation`:
   http://turbo-hipster.rtfd.org/

.. _FormPost: http://docs.openstack.org/developer/swift/misc.html#module-swift.common.middleware.formpost

.. _launchers:

Launchers
=========

Zuul has a modular architecture for launching jobs.  Currently, the
only supported module interfaces with Gearman_.  This design allows
any system to run jobs for Zuul simply by interfacing with a Gearman
server.  The recommended way of integrating a new job-runner with Zuul
is via this method.

If Gearman is unsuitable, Zuul may be extended with a new launcher
module.  Zuul makes very few assumptions about the interface to a
launcher -- if it can trigger jobs, cancel them, and receive success
or failure reports, it should be able to be used with Zuul.  Patches
to this effect are welcome.

Zuul Parameters
---------------

Zuul will pass some parameters with every job it launches.  These are
for workers to be able to get the repositories into the state they are
intended to be tested in.  Builds can be triggered either by an action
on a change or by a reference update.  Both events share a common set
of parameters and more specific parameters as follows:

Common parameters
~~~~~~~~~~~~~~~~~

**ZUUL_UUID**
  Zuul provided key to link builds with Gerrit events.
**ZUUL_REF**
  Zuul provided ref that includes commit(s) to build.
**ZUUL_COMMIT**
  The commit SHA1 at the head of ZUUL_REF.
**ZUUL_PROJECT**
  The project that triggered this build.
**ZUUL_PIPELINE**
  The Zuul pipeline that is building this job.
**ZUUL_URL**
  The URL for the zuul server as configured in zuul.conf.
  A test runner may use this URL as the basis for fetching
  git commits.
**BASE_LOG_PATH**
  zuul suggests a path to store and address logs. This is deterministic
  and hence useful for where you want workers to upload to a specific
  destination or need them to have a specific final URL you can link to
  in advanced. For changes it is:
  "last-two-digits-of-change/change-number/patchset-number".
  For reference updates it is: "first-two-digits-of-newrev/newrev"
**LOG_PATH**
  zuul also suggests a unique path for logs to the worker. This is
  "BASE_LOG_PATH/pipeline-name/job-name/uuid"
**ZUUL_VOTING**
  Whether Zuul considers this job voting or not.  Note that if Zuul is
  reconfigured during the run, the voting status of a job may change
  and this value will be out of date.  Values are '1' if voting, '0'
  otherwise.

Change related parameters
~~~~~~~~~~~~~~~~~~~~~~~~~

The following additional parameters will only be provided for builds
associated with changes (i.e., in response to patchset-created or
comment-added events):

**ZUUL_BRANCH**
  The target branch for the change that triggered this build.
**ZUUL_CHANGE**
  The Gerrit change ID for the change that triggered this build.
**ZUUL_CHANGES**
  A caret character separated list of the changes upon which this build
  is dependent upon in the form of a colon character separated list
  consisting of project name, target branch, and revision ref.
**ZUUL_CHANGE_IDS**
  All of the Gerrit change IDs that are included in this build (useful
  when the DependentPipelineManager combines changes for testing).
**ZUUL_PATCHSET**
  The Gerrit patchset number for the change that triggered this build.

Reference updated parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following additional parameters will only be provided for
post-merge (ref-updated) builds:

**ZUUL_OLDREV**
  The SHA1 of the old revision at this ref (recall the ref name is
  in ZUUL_REF).
**ZUUL_NEWREV**
  The SHA1 of the new revision at this ref (recall the ref name is
  in ZUUL_REF).
**ZUUL_SHORT_OLDREV**
  The shortened (7 character) SHA1 of the old revision.
**ZUUL_SHORT_NEWREV**
  The shortened (7 character) SHA1 of the new revision.

Unset revisions default to 00000000000000000000000000000000.

Examples:

When a reference is created::

    ZUUL_OLDREV=00000000000000000000000000000000
    ZUUL_NEWREV=123456789abcdef123456789abcdef12
    ZUUL_SHORT_OLDREV=0000000
    ZUUL_SHORT_NEWREV=1234567

When a reference is deleted::

    ZUUL_OLDREV=123456789abcdef123456789abcdef12
    ZUUL_NEWREV=00000000000000000000000000000000
    ZUUL_SHORT_OLDREV=1234567
    ZUUL_SHORT_NEWREV=0000000

And finally a reference being altered::

    ZUUL_OLDREV=123456789abcdef123456789abcdef12
    ZUUL_NEWREV=abcdef123456789abcdef123456789ab
    ZUUL_SHORT_OLDREV=1234567
    ZUUL_SHORT_NEWREV=abcdef1

Your jobs can check whether the parameters are ``000000`` to act
differently on each kind of event.

Swift parameters
~~~~~~~~~~~~~~~~

If swift information has been configured for the job zuul will also
provide signed credentials for the builder to upload results and
assets into containers using the `FormPost`_ middleware.

Each zuul container/instruction set will contain each of the following
parameters where $NAME is the ``name`` defined in the layout.

*SWIFT_$NAME_URL*
  The swift destination URL. This will be the entire URL including
  the AUTH, container and path prefix (folder).
*SWIFT_$NAME_HMAC_BODY*
  The information signed in the HMAC body. The body is as follows::

    PATH TO OBJECT PREFIX (excluding domain)
    BLANK LINE (zuul implements no form redirect)
    MAX FILE SIZE
    MAX FILE COUNT
    SIGNATURE EXPIRY

*SWIFT_$NAME_SIGNATURE*
  The HMAC body signed with the configured key.
*SWIFT_$NAME_LOGSERVER_PREFIX*
  The URL to prepend to the object path when returning the results
  from a build.

Gearman
-------

Gearman_ is a general-purpose protocol for distributing jobs to any
number of workers.  Zuul works with Gearman by sending specific
information with job requests to Gearman, and expects certain
information to be returned on completion.  This protocol is described
in `Zuul-Gearman Protocol`_.

In order for Zuul to run any jobs, you will need a running Gearman
server.  Zuul includes a Gearman server, and it is recommended that it
be used as it supports the following features needed by Zuul:

* Canceling jobs in the queue (admin protocol command "cancel job").
* Strict FIFO queue operation (gearmand's round-robin mode may be
  sufficient, but is untested).

To enable the built-in server, see the ``gearman_server`` section of
``zuul.conf``.  Be sure that the host allows connections from Zuul and
any workers (e.g., Jenkins masters) on TCP port 4730, and nowhere else
(as the Gearman protocol does not include any provision for
authentication).

Gearman Jenkins Plugin
~~~~~~~~~~~~~~~~~~~~~~

The `Gearman Jenkins Plugin`_ makes it easy to use Jenkins with Zuul
by providing an interface between Jenkins and Gearman.  In this
configuration, Zuul asks Gearman to run jobs, and Gearman can then
distribute those jobs to any number of Jenkins systems (including
multiple Jenkins masters).

The `Gearman Plugin`_ can be installed in Jenkins in order to
facilitate Jenkins running jobs for Zuul.  Install the plugin and
configure it with the hostname or IP address of your Gearman server
and the port on which it is listening (4730 by default).  It will
automatically register all known Jenkins jobs as functions that Zuul
can invoke via Gearman.

Any number of masters can be configured in this way, and Gearman will
distribute jobs to all of them as appropriate.

No special Jenkins job configuration is needed to support triggering
by Zuul.

The Gearman Plugin will ensure the `Zuul Parameters`_ are supplied as
Jenkins build parameters, so they will be available for use in the job
configuration as well as to the running job as environment variables.

Jenkins git plugin configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In order to test the correct build, configure the Jenkins Git SCM
plugin as follows::

  Source Code Management:
    Git
      Repositories:
        Repository URL:  <your Gerrit or Zuul repository URL>
          Advanced:
            Refspec: ${ZUUL_REF}
      Branches to build:
        Branch Specifier: ${ZUUL_COMMIT}
            Advanced:
            Clean after checkout: True

That should be sufficient for a job that only builds a single project.
If you have multiple interrelated projects (i.e., they share a Zuul
Change Queue) that are built together, you may be able to configure
the Git plugin to prepare them, or you may chose to use a shell script
instead.  As an example, the OpenStack project uses the following
script to prepare the workspace for its integration testing:

  https://git.openstack.org/cgit/openstack-infra/devstack-gate/tree/devstack-vm-gate-wrap.sh

Turbo Hipster Worker
~~~~~~~~~~~~~~~~~~~~

As an alternative to Jenkins, `Turbo-Hipster`_ is a small python
project designed specifically as a zuul job worker which can be
registered with gearman as a job runner. Please see the
`Turbo-Hipster Documentation`_ for details on how to set it up.

Zuul-Gearman Protocol
~~~~~~~~~~~~~~~~~~~~~

This section is only relevant if you intend to implement a new kind of
worker that runs jobs for Zuul via Gearman.  If you just want to use
Jenkins, see `Gearman Jenkins Plugin`_ instead.

The Zuul protocol as used with Gearman is as follows:

Starting Builds
^^^^^^^^^^^^^^^

To start a build, Zuul invokes a Gearman function with the following
format:

  build:FUNCTION_NAME

where **FUNCTION_NAME** is the name of the job that should be run.  If
the job should run on a specific node (or class of node), Zuul will
instead invoke:

  build:FUNCTION_NAME:NODE_NAME

where **NODE_NAME** is the name or class of node on which the job
should be run.  This can be specified by setting the ZUUL_NODE
parameter in a parameter-function (see :ref:`includes` section in
:ref:`zuulconf`).

Zuul sends the ZUUL_* parameters described in `Zuul Parameters`_
encoded in JSON format as the argument included with the
SUBMIT_JOB_UNIQ request to Gearman.  A unique ID (equal to the
ZUUL_UUID parameter) is also supplied to Gearman, and is accessible as
an added Gearman parameter with GRAB_JOB_UNIQ.

When a Gearman worker starts running a job for Zuul, it should
immediately send a WORK_DATA packet with the following information
encoded in JSON format:

**name**
  The name of the job.

**number**
  The build number (unique to this job).

**manager**
  A unique identifier associated with the Gearman worker that can
  abort this build.  See `Stopping Builds`_ for more information.

**url** (optional)
  The URL with the status or results of the build.  Will be used in
  the status page and the final report.

To help with debugging builds a worker may send back some optional
metadata:

**worker_name** (optional)
  The name of the worker.

**worker_hostname** (optional)
  The hostname of the worker.

**worker_ips** (optional)
  A list of IPs for the worker.

**worker_fqdn** (optional)
  The FQDN of the worker.

**worker_program** (optional)
  The program name of the worker. For example Jenkins or turbo-hipster.

**worker_version** (optional)
  The version of the software running the job.

**worker_extra** (optional)
  A dictionary of any extra metadata you may want to pass along.

It should then immediately send a WORK_STATUS packet with a value of 0
percent complete.  It may then optionally send subsequent WORK_STATUS
packets with updated completion values.

When the build is complete, it should send a final WORK_DATA packet
with the following in JSON format:

**result**
  Either the string 'SUCCESS' if the job succeeded, or any other value
  that describes the result if the job failed.

Finally, it should send either a WORK_FAIL or WORK_COMPLETE packet as
appropriate.  A WORK_EXCEPTION packet will be interpreted as a
WORK_FAIL, but the exception will be logged in Zuul's error log.

Stopping Builds
^^^^^^^^^^^^^^^

If Zuul needs to abort a build already in progress, it will invoke the
following function through Gearman:

  stop:MANAGER_NAME

Where **MANAGER_NAME** is the name of the manager worker supplied in
the initial WORK_DATA packet when the job started.  This is used to
direct the stop: function invocation to the correct Gearman worker
that is capable of stopping that particular job.  The argument to the
function should be the following encoded in JSON format:

**name**
  The job name of the build to stop.

**number**
  The build number of the build to stop.

The original job is expected to complete with a WORK_DATA and
WORK_FAIL packet as described in `Starting Builds`_.

Build Descriptions
^^^^^^^^^^^^^^^^^^

In order to update the job running system with a description of the
current state of all related builds, the job runner may optionally
implement the following Gearman function:

  set_description:MANAGER_NAME

Where **MANAGER_NAME** is used as described in `Stopping Builds`_.
The argument to the function is the following encoded in JSON format:

**name**
  The job name of the build to describe.

**number**
  The build number of the build to describe.

**html_description**
  The description of the build in HTML format.
