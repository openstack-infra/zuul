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
      :type: gauge

      The number of builds starting on this executor.  These are
      builds which have not yet begun their first pre-playbook.

   .. stat:: running_builds
      :type: gauge

      The number of builds currently running on this executor.  This
      includes starting builds.

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

   .. stat:: pct_used_ram
      :type: gauge

      The used RAM (excluding buffers and cache) on this executor, as
      a percentage multiplied by 100.

.. stat:: zuul.nodepool

   Holds metrics related to Zuul requests from Nodepool.

   .. stat:: requested
      :type: counter

      Incremented each time a node request is submitted to Nodepool.

      .. stat:: label.<label>
         :type: counter

         Incremented each time a request for a specific label is
         submitted to Nodepool.

      .. stat:: size.<size>
         :type: counter

         Incremented each time a request of a specific size is submitted
         to Nodepool.  For example, a request for 3 nodes would use the
         key ``zuul.nodepool.requested.size.3``.

   .. stat:: canceled
      :type: counter, timer

      The counter is incremented each time a node request is canceled
      by Zuul.  The timer records the elapsed time from request to
      cancelation.

      .. stat:: label.<label>
         :type: counter, timer

         The same, for a specific label.

      .. stat:: size.<size>
         :type: counter, timer

         The same, for a specific request size.

   .. stat:: fulfilled
      :type: counter, timer

      The counter is incremented each time a node request is fulfilled
      by Nodepool.  The timer records the elapsed time from request to
      fulfillment.

      .. stat:: label.<label>
         :type: counter, timer

         The same, for a specific label.

      .. stat:: size.<size>
         :type: counter, timer

         The same, for a specific request size.

   .. stat:: failed
      :type: counter, timer

      The counter is incremented each time Nodepool fails to fulfill a
      node request.  The timer records the elapsed time from request
      to failure.

      .. stat:: label.<label>
         :type: counter, timer

         The same, for a specific label.

      .. stat:: size.<size>
         :type: counter, timer

         The same, for a specific request size.

   .. stat:: current_requests
      :type: gauge

      The number of outstanding nodepool requests from Zuul.

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

      The number of merge jobs queued.

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

      The number of executor jobs queued.


As an example, given a job named `myjob` in `mytenant` triggered by a
change to `myproject` on the `master` branch in the `gate` pipeline
which took 40 seconds to build, the Zuul scheduler will emit the
following statsd events:

  * ``zuul.tenant.mytenant.pipeline.gate.project.example_com.myproject.master.job.myjob.SUCCESS`` +1
  * ``zuul.tenant.mytenant.pipeline.gate.project.example_com.myproject.master.job.myjob.SUCCESS``  40 seconds
  * ``zuul.tenant.mytenant.pipeline.gate.all_jobs`` +1
