:title: Zuul Driver

Zuul
====

The Zuul driver supports triggers only.  It is used for triggering
pipelines based on internal Zuul events.

Trigger Configuration
---------------------

Zuul events don't require a special connection or driver. Instead they
can simply be used by listing ``zuul`` as the trigger.

.. attr:: pipeline.trigger.zuul

   The Zuul trigger supports the following attributes:

   .. attr:: event
      :required:

      The event name.  Currently supported events:

      .. value:: project-change-merged

         When Zuul merges a change to a project, it generates this
         event for every open change in the project.

         .. warning::

            Triggering on this event can cause poor performance when
            using the GitHub driver with a large number of
            installations.

      .. value:: parent-change-enqueued

         When Zuul enqueues a change into any pipeline, it generates
         this event for every child of that change.

   .. attr:: pipeline

      Only available for ``parent-change-enqueued`` events.  This is
      the name of the pipeline in which the parent change was
      enqueued.
