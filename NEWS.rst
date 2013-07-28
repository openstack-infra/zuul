Since 1.3.0:

* The Jenkins launcher is replaced with Gearman launcher.  An internal
  Gearman server is provided, and there is a Gearman plugin for
  Jenkins, so migration to the new system should be fairly
  straightforward.  See the Launchers section of the documentation for
  details.

* The custom parameter function signature now takes a QueueItem as the
  first argument, rather than the Change.  The QueueItem has the full
  context for why the change is being run (including the pipeline,
  items ahead and behind, etc.).  The Change is still available via
  the "change" attribute on the QueueItem.

* The default behavior is now to immediately dequeue changes that have
  merge conflicts, even those not at the head of the queue.  To enable
  the old behavior (which would wait until the conflicting change was
  at the head before dequeuing it), see the new "dequeue-on-conflict"
  option.

* Some statsd keys have changed in a backwards incompatible way:
  * The counters and timers of the form zuul.job.{name} is now split
    into several keys of the form:
    zuul.pipeline.{pipeline-name}.job.{job-name}.{result}
  * Job names in statsd keys now have the '_' character substituted
    for the '.' character.
