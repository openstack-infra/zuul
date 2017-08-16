:title: Monitoring

Monitoring
==========

Statsd reporting
----------------

Zuul comes with support for the statsd protocol, when enabled and configured
(see below), the Zuul scheduler will emit raw metrics to a statsd receiver
which let you in turn generate nice graphics.

Configuration
~~~~~~~~~~~~~

Statsd support uses the statsd python module. Note that Zuul will start without
the statsd python module, so an existing Zuul installation may be missing it.

The configuration is done via environment variables STATSD_HOST and
STATSD_PORT. They are interpreted by the statsd module directly and there is no
such parameter in zuul.conf yet. Your init script will have to initialize both
of them before executing Zuul.

Your init script most probably loads a configuration file named
``/etc/default/zuul`` which would contain the environment variables::

  $ cat /etc/default/zuul
  STATSD_HOST=10.0.0.1
  STATSD_PORT=8125

Metrics
~~~~~~~

These metrics are emitted by the Zuul :ref:`scheduler`:

.. stat:: gerrit.event.<type>
   :type: counter

   Gerrit emits different kinds of messages over its `stream-events`
   interface.  Zuul will report counters for each type of event it
   receives from Gerrit.

   Refer to your Gerrit installation documentation for a complete
   list of Gerrit event types.

.. stat:: zuul.pipeline

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

      .. stat:: job

         Subtree detailing per jobs statistics:

         .. stat:: <jobname>

            The triggered job name.

            .. stat:: <result>
               :type: counter, timer

               A counter for each type of result (e.g., ``SUCCESS`` or
               ``FAILURE``, ``ERROR``, etc.) for the job.  If the
               result is ``SUCCESS`` or ``FAILURE``, Zuul will
               additionally report the duration of the build as a
               timer.

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

      .. stat:: <project>

         This hierarchy holds more specific metrics for each project
         participating in the pipeline.  If the project name contains
         a ``/`` character, it will be replaced with a ``.``.

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

As an example, given a job named `myjob` triggered by the `gate` pipeline
which took 40 seconds to build, the Zuul scheduler will emit the following
statsd events:

  * ``zuul.pipeline.gate.job.myjob.SUCCESS`` +1
  * ``zuul.pipeline.gate.job.myjob``  40 seconds
  * ``zuul.pipeline.gate.all_jobs`` +1
