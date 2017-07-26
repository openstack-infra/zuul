:title: Zuul Driver

Zuul
====

The Zuul driver supports triggers only.  It is used for triggering
pipelines based on internal Zuul events.

Trigger Configuration
---------------------

Zuul events don't require a special connection or driver. Instead they
can simply be used by listing **zuul** as the trigger.

**event**
  The event name.  Currently supported:

  *project-change-merged* when Zuul merges a change to a project, it
  generates this event for every open change in the project.

  *parent-change-enqueued* when Zuul enqueues a change into any
  pipeline, it generates this event for every child of that
  change.

**pipeline**
  Only available for ``parent-change-enqueued`` events.  This is the
  name of the pipeline in which the parent change was enqueued.
