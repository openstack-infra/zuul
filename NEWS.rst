Since 1.2.0:

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
