Data Model
==========

It all starts with the :py:class:`~zuul.model.Pipeline`. A Pipeline is the
basic organizational structure that everything else hangs off.

.. autoclass:: zuul.model.Pipeline

Pipelines have a configured
:py:class:`~zuul.manager.PipelineManager` which controlls how
the :py:class:`Ref <zuul.model.Ref>` objects are enqueued and
processed.

There are currently two,
:py:class:`~zuul.manager.dependent.DependentPipelineManager` and
:py:class:`~zuul.manager.independent.IndependentPipelineManager`

.. autoclass:: zuul.manager.PipelineManager
.. autoclass:: zuul.manager.dependent.DependentPipelineManager
.. autoclass:: zuul.manager.independent.IndependentPipelineManager

A :py:class:`~zuul.model.Pipeline` has one or more
:py:class:`~zuul.model.ChangeQueue` objects.

.. autoclass:: zuul.model.ChangeQueue

A :py:class:`~zuul.model.Job` represents the definition of what to do. A
:py:class:`~zuul.model.Build` represents a single run of a
:py:class:`~zuul.model.Job`. A :py:class:`~zuul.model.JobGraph` is used to
encapsulate the dependencies between one or more :py:class:`~zuul.model.Job`
objects.

.. autoclass:: zuul.model.Job
.. autoclass:: zuul.model.JobGraph
.. autoclass:: zuul.model.Build

The :py:class:`~zuul.manager.base.PipelineManager` enqueues each
:py:class:`Ref <zuul.model.Ref>` into the
:py:class:`~zuul.model.ChangeQueue` in a :py:class:`~zuul.model.QueueItem`.

.. autoclass:: zuul.model.QueueItem

As the Changes are processed, each :py:class:`~zuul.model.Build` is put into
a :py:class:`~zuul.model.BuildSet`

.. autoclass:: zuul.model.BuildSet

Changes
~~~~~~~

.. autoclass:: zuul.model.Change
.. autoclass:: zuul.model.Ref

Filters
~~~~~~~

.. autoclass:: zuul.model.RefFilter
.. autoclass:: zuul.model.EventFilter


Tenants
~~~~~~~

An abide is a collection of tenants.

.. autoclass:: zuul.model.Tenant
.. autoclass:: zuul.model.UnparsedAbideConfig
.. autoclass:: zuul.model.UnparsedConfig
.. autoclass:: zuul.model.ParsedConfig

Other Global Objects
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: zuul.model.Project
.. autoclass:: zuul.model.Layout
.. autoclass:: zuul.model.RepoFiles
.. autoclass:: zuul.model.Worker
.. autoclass:: zuul.model.TriggerEvent
