Testing
=======

Zuul provides an extensive framework for performing functional testing
on the system from end-to-end with major external components replaced
by fakes for ease of use and speed.

Test classes that subclass :py:class:`~tests.base.ZuulTestCase` have
access to a number of attributes useful for manipulating or inspecting
the environment being simulated in the test:

.. autofunction:: tests.base.simple_layout

.. autoclass:: tests.base.ZuulTestCase
   :members:

.. autoclass:: tests.base.FakeGerritConnection
   :members:
   :inherited-members:

.. autoclass:: tests.base.FakeGearmanServer
   :members:

.. autoclass:: tests.base.RecordingExecutorServer
   :members:

.. autoclass:: tests.base.FakeBuild
   :members:

.. autoclass:: tests.base.BuildHistory
   :members:
