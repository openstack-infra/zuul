:title: Monitoring

Monitoring
==========

.. _statsd:

Statsd reporting
----------------

Zuul comes with support for the statsd protocol, when enabled and configured
(see below), the Zuul scheduler will emit raw metrics to a statsd receiver
which let you in turn generate nice graphics.

Configuration
~~~~~~~~~~~~~

Statsd support uses the ``statsd`` python module.  Note that support
is optional and Zuul will start without the statsd python module
present.

Configuration is in the :attr:`statsd` section of ``zuul.conf``.

Metrics
~~~~~~~

These metrics are emitted by the Zuul :ref:`scheduler`:

.. stat:: zuul.event.<driver>.<type>
   :type: counter

   Zuul will report counters for each type of event it receives from
   each of its configured drivers.

.. stat:: zuul.tenant.<tenant>.pipeline

   Holds metrics specific to jobs. This hierarchy includes:

   .. stat:: <pipeline name>

      A set of metrics for each pipeline named as defined in the Zuul
      config.

      .. stat:: all_jobs
         :type: counter

         Number of jobs triggered by the pipeline.

      .. stat:: current_changes
         :type: gauge

         The number of items currently being processed by this
         pipeline.

      .. stat:: project

         This hierarchy holds more specific metrics for each project
         participating in the pipeline.

         .. stat:: <canonical_hostname>

            The canonical hostname for the triggering project.
            Embedded ``.`` characters will be translated to ``_``.

            .. stat:: <project>

               The name of the triggering project.  Embedded ``/`` or
               ``.`` characters will be translated to ``_``.

               .. stat:: <branch>

                  The name of the triggering branch.  Embedded ``/`` or
                  ``.`` characters will be translated to ``_``.

                  .. stat:: job

                     Subtree detailing per-project job statistics:

                     .. stat:: <jobname>

                        The triggered job name.

                        .. stat:: <result>
                           :type: counter, timer

                           A counter for each type of result (e.g., ``SUCCESS`` or
                           ``FAILURE``, ``ERROR``, etc.) for the job.  If the
                           result is ``SUCCESS`` or ``FAILURE``, Zuul will
                           additionally report the duration of the build as a
                           timer.

                  .. stat:: current_changes
                     :type: gauge

                     The number of items of this project currently being
                     processed by this pipeline.

                  .. stat:: resident_time
                     :type: timer

                     A timer metric reporting how long each item for this
                     project has been in the pipeline.

                  .. stat:: total_changes
                     :type: counter

                     The number of changes for this project processed by the
                     pipeline since Zuul started.

      .. stat:: resident_time
         :type: timer

         A timer metric reporting how long each item has been in the
         pipeline.

      .. stat:: total_changes
         :type: counter

         The number of changes processed by the pipeline since Zuul
         started.

      .. stat:: wait_time
         :type: timer

         How long each item spent in the pipeline before its first job
         started.

.. stat:: zuul.executor.<executor>

   Holds metrics emitted by individual executors.  The ``<executor>``
   component of the key will be replaced with the hostname of the
   executor.

   .. stat:: merger.<result>
      :type: counter

      Incremented to represent the status of a Zuul executor's merger
      operations. ``<result>`` can be either ``SUCCESS`` or ``FAILURE``.
      A failed merge operation which would be accounted for as a ``FAILURE``
      is what ends up being returned by Zuul as a ``MERGER_FAILURE``.

   .. stat:: builds
      :type: counter

      Incremented each time the executor starts a build.

   .. stat:: starting_builds
      :type: gauge, timer

      The number of builds starting on this executor and a timer containing
      how long jobs were in this state. These are builds which have not yet
      begun their first pre-playbook.

      The timer needs special thoughts when interpreting it because it
      aggregates all jobs. It can be useful when aggregating it over a longer
      period of time (maybe a day) where fast rising graphs could indicate e.g.
      IO problems of the machines the executors are running on. But it has to
      be noted that a rising graph also can indicate a higher usage of complex
      jobs using more required projects. Also comparing several executors might
      give insight if the graphs differ a lot from each other. Typically the
      jobs are equally distributed over all executors (in the same zone when
      using the zone feature) and as such the starting jobs timers (aggregated
      over a large enough interval) should not differ much.

   .. stat:: running_builds
      :type: gauge

      The number of builds currently running on this executor.  This
      includes starting builds.

   .. stat:: paused_builds
      :type: gauge

      The number of currently paused builds on this executor.

   .. stat:: phase

      Subtree detailing per-phase execution statistics:

      .. stat:: <phase>

         ``<phase>`` represents a phase in the execution of a job.
         This can be an *internal* phase (such as ``setup`` or ``cleanup``) as
         well as *job* phases such as ``pre``, ``run`` or ``post``.

         .. stat:: <result>
            :type: counter

            A counter for each type of result.
            These results do not, by themselves, determine the status of a build
            but are indicators of the exit status provided by Ansible for the
            execution of a particular phase.

            Example of possible counters for each phase are: ``RESULT_NORMAL``,
            ``RESULT_TIMED_OUT``, ``RESULT_UNREACHABLE``, ``RESULT_ABORTED``.

   .. stat:: load_average
      :type: gauge

      The one-minute load average of this executor, multiplied by 100.

   .. stat:: pause
      :type: gauge

      Indicates if the executor is paused. 1 means paused else 0.

   .. stat:: pct_used_ram
      :type: gauge

      The used RAM (excluding buffers and cache) on this executor, as
      a percentage multiplied by 100.

  .. stat:: pct_used_ram_cgroup
     :type: gauge

     The used RAM (excluding buffers and cache) on this executor allowed by
     the cgroup, as percentage multiplied by 100.

.. stat:: zuul.nodepool.requests

   Holds metrics related to Zuul requests and responses from Nodepool.

   States are one of:

      *requested*
        Node request submitted by Zuul to Nodepool
      *canceled*
        Node request was canceled by Zuul
      *failed*
        Nodepool failed to fulfill a node request
      *fulfilled*
        Nodes were assigned by Nodepool

   .. stat:: <state>
      :type: timer

      Records the elapsed time from request to completion for states
      `failed` and `fulfilled`.  For example,
      ``zuul.nodepool.request.fulfilled.mean`` will give the average
      time for all fulfilled requests within each ``statsd`` flush
      interval.

      A lower value for `fulfilled` requests is better.  Ideally,
      there will be no `failed` requests.

   .. stat:: <state>.total
      :type: counter

      Incremented when nodes are assigned or removed as described in
      the states above.

   .. stat:: <state>.size.<size>
      :type: counter, timer

      Increments for the node count of each request.  For example, a
      request for 3 nodes would use the key
      ``zuul.nodepool.requests.requested.size.3``; fulfillment of 3
      node requests can be tracked with
      ``zuul.nodepool.requests.fulfilled.size.3``.

      The timer is implemented for ``fulfilled`` and ``failed``
      requests.  For example, the timer
      ``zuul.nodepool.requests.failed.size.3.mean`` gives the average
      time of 3-node failed requests within the ``statsd`` flush
      interval.  A lower value for `fulfilled` requests is better.
      Ideally, there will be no `failed` requests.

   .. stat:: <state>.label.<label>
      :type: counter, timer

      Increments for the label of each request.  For example, requests
      for `centos7` nodes could be tracked with
      ``zuul.nodepool.requests.requested.centos7``.

      The timer is implemented for ``fulfilled`` and ``failed``
      requests.  For example, the timer
      ``zuul.nodepool.requests.fulfilled.label.centos7.mean`` gives
      the average time of ``centos7`` fulfilled requests within the
      ``statsd`` flush interval.  A lower value for `fulfilled`
      requests is better.  Ideally, there will be no `failed`
      requests.

   .. stat:: current_requests
      :type: gauge

      The number of outstanding nodepool requests from Zuul.  Ideally
      this will be at zero, meaning all requests are fulfilled.
      Persistently high values indicate more testing node resources
      would be helpful.

.. stat:: zuul.mergers

   Holds metrics related to Zuul mergers.

   .. stat:: online
      :type: gauge

      The number of Zuul merger processes online.

   .. stat:: jobs_running
      :type: gauge

      The number of merge jobs running.

   .. stat:: jobs_queued
      :type: gauge

      The number of merge jobs waiting for a merger.  This should
      ideally be zero; persistent higher values indicate more merger
      resources would be useful.

.. stat:: zuul.executors

   Holds metrics related to Zuul executors.

   .. stat:: online
      :type: gauge

      The number of Zuul executor processes online.

   .. stat:: accepting
      :type: gauge

      The number of Zuul executor processes accepting new jobs.

   .. stat:: jobs_running
      :type: gauge

      The number of executor jobs running.

   .. stat:: jobs_queued
      :type: gauge

      The number of jobs allocated nodes, but queued waiting for an
      executor to run on.  This should ideally be at zero; persistent
      higher values indicate more executor resources would be useful.

.. stat:: zuul.geard

   Gearman job distribution statistics.  Gearman jobs encompass the
   wide variety of distributed jobs running within the scheduler and
   across mergers and executors.  These stats are emitted by the `gear
   <https://pypi.org/project/gear/>`__ library.

   .. stat:: running
      :type: gauge

      Jobs that Gearman has actively running.  The longest running
      jobs will usually relate to active job execution so you would
      expect this to have a lower bound around there.  Note this may
      be lower than active nodes, as a multiple-node job will only
      have one active Gearman job.

   .. stat:: waiting
      :type: gauge

      Jobs waiting in the gearman queue.  This would be expected to be
      around zero; note that this is *not* related to the backlogged
      queue of jobs waiting for a node allocation (node allocations
      are via Zookeeper).  If this is unexpectedly high, see
      :ref:`debug_gearman` for queue debugging tips to find out which
      particular function calls are waiting.

   .. stat:: total
      :type: gauge

      The sum of the `running` and `waiting` jobs.

As an example, given a job named `myjob` in `mytenant` triggered by a
change to `myproject` on the `master` branch in the `gate` pipeline
which took 40 seconds to build, the Zuul scheduler will emit the
following statsd events:

  * ``zuul.tenant.mytenant.pipeline.gate.project.example_com.myproject.master.job.myjob.SUCCESS`` +1
  * ``zuul.tenant.mytenant.pipeline.gate.project.example_com.myproject.master.job.myjob.SUCCESS``  40 seconds
  * ``zuul.tenant.mytenant.pipeline.gate.all_jobs`` +1
