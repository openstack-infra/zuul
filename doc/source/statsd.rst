:title: Statsd reporting

Statsd reporting
================

Zuul comes with support for the statsd protocol, when enabled and configured
(see below), the Zuul scheduler will emit raw metrics to a statsd receiver
which let you in turn generate nice graphics. An example is OpenStack Zuul
status page: http://status.openstack.org/zuul/

Configuration
-------------

Statsd support uses the statsd python module. Note that Zuul will start without
the statsd python module, so an existing Zuul installation may be missing it.

The configuration is done via environment variables STATSD_HOST and
STATSD_PORT. They are interpreted by the statsd module directly and there is no
such parameter in zuul.conf yet. Your init script will have to initialize both
of them before launching Zuul.

Your init script most probably loads a configuration file named
``/etc/default/zuul`` which would contain the environment variables::

  $ cat /etc/default/zuul
  STATSD_HOST=10.0.0.1
  STATSD_PORT=8125

Metrics
-------

The metrics are emitted by the Zuul scheduler (`zuul/scheduler.py`):

**gerrit.event.<type> (counters)**
  Gerrit emits different kind of message over its `stream-events` interface. As
  a convenience, Zuul emits metrics to statsd which save you from having to use
  a different daemon to measure Gerrit events.
  The Gerrit events have different types defined by Gerrit itself, Zuul will
  relay any type of event reusing the name defined by Gerrit. Some of the
  events emitted are:

    * patchset-created
    * draft-published
    * change-abandonned
    * change-restored
    * change-merged
    * merge-failed
    * comment-added
    * ref-updated
    * reviewer-added

  Refer to your Gerrit installation documentation for an exhaustive list of
  Gerrit event types.

**zuul.node_type.**
  Holds metrics specifc to build nodes per label. The hierarchy is:

    #. **<build node label>** each of the labels associated to a build in
           Jenkins. It contains:

      #. **job.<jobname>** subtree detailing per job statistics:

        #. **wait_time** counter and timer of the wait time, with the
                   difference of the job start time and the launch time, in
                   milliseconds.

**zuul.pipeline.**
  Holds metrics specific to jobs. The hierarchy is:

    #. **<pipeline name>** as defined in your `layout.yaml` file (ex: `gate`,
                         `test`, `publish`). It contains:

      #. **all_jobs** counter of jobs triggered by the pipeline.
      #. **current_changes** A gauge for the number of Gerrit changes being
               processed by this pipeline.
      #. **job** subtree detailing per jobs statistics:

        #. **<jobname>** The triggered job name.
        #. **<build result>** Result as defined in your triggering system. For
                 Jenkins that would be SUCCESS, FAILURE, UNSTABLE, LOST.  The
                 metrics holds both an increasing counter and a timing
                 reporting the duration of the build. Whenever the result is a
                 SUCCESS or FAILURE, Zuul will additionally report the duration
                 of the build as a timing event.

      #. **resident_time** timing representing how long the Change has been
               known by Zuul (which includes build time and Zuul overhead).
      #. **total_changes** counter of the number of change proceeding since
               Zuul started.
      #. **wait_time** counter and timer of the wait time, with the difference
               of the job start time and the launch time, in milliseconds.

  Additionally, the `zuul.pipeline.<pipeline name>` hierarchy contains
  `current_changes` (gauge), `resident_time` (timing) and `total_changes`
  (counter) metrics for each projects. The slash separator used in Gerrit name
  being replaced by dots.

  As an example, given a job named `myjob` triggered by the `gate` pipeline
  which took 40 seconds to build, the Zuul scheduler will emit the following
  statsd events:

    * `zuul.pipeline.gate.job.myjob.SUCCESS` +1
    * `zuul.pipeline.gate.job.myjob`  40 seconds
    * `zuul.pipeline.gate.all_jobs` +1
