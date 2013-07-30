Since 1.3.0:

* The Jenkins launcher is replaced with Gearman launcher.  An internal
  Gearman server is provided, and there is a Gearman plugin for
  Jenkins, so migration to the new system should be fairly
  straightforward.  See the Launchers section of the documentation for
  details.

* The custom parameter function signature has changed.  It now takes a
  QueueItem as the first argument, rather than the Change.  The
  QueueItem has the full context for why the change is being run
  (including the pipeline, items ahead and behind, etc.).  The Change
  is still available via the "change" attribute on the QueueItem.  The
  second argument is now the Job that is about to be run, and the
  parameter dictionary is shifted to the third position.

* The ZUUL_SHORT_* parameters have been removed (the same
  functionality may be achieved with a custom parameter function that
  matches all jobs).

* Multiple triggers are now supported, in principle (though only
  Gerrit is defined currently).  Your layout.yaml file will need to
  change to add the key "gerrit:" inside of the "triggers:" list to
  specify a Gerrit trigger (and facilitate adding other kinds of
  triggers later).  See the sample layout.yaml.

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
