Since 2.0.0:

* The push_change_refs option which specified that Zuul refs should be
  pushed to Gerrit has been removed.

* Git merge operations are now performed in a separate process.  Run
  at least one instance of the ``zuul-merger`` program which is now
  included.  Any number of Zuul-Mergers may be run in order to
  distribute the work of speculatively merging changes into git and
  serving the results to test workers.  This system is designed to
  scale out to many servers, but one instance may be co-located with
  the Zuul server in smaller deployments.  Several configuration
  options have moved from the ``zuul`` section to ``merger``.

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

* Multiple triggers are now supported (currently Gerrit and a simple
  Timer trigger are supported).  Your layout.yaml file will need to
  change to add the key "gerrit:" inside of the "triggers:" list to
  specify a Gerrit trigger (and facilitate adding other kinds of
  triggers later).  See the sample layout.yaml and Zuul section of the
  documentation.

* Some statsd keys have changed in a backwards incompatible way:
  * The counters and timers of the form zuul.job.{name} is now split
    into several keys of the form:
    zuul.pipeline.{pipeline-name}.job.{job-name}.{result}
  * Job names in statsd keys now have the '_' character substituted
    for the '.' character.

* The layout.yaml structure has changed to introduce configurable
  reporters. This requires restructuring the start/success/failure
  actions to include a dictionary of reporters and their parameters.
  See reporters in the docs and layout.yaml-sample.

* The zuul_url configuration option is required in zuul.conf.  It
  specifies the URL of the git repositories that should be used by
  workers when fetching Zuul refs and is passed to the workers as the
  ZUUL_URL parameter.  It should probably be set to
  "http://zuul-host-name/p/".
