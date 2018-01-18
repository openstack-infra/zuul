Triggers
========

Triggers must inherit from :py:class:`~zuul.trigger.BaseTrigger` and, at a minimum,
implement the :py:meth:`~zuul.trigger.BaseTrigger.getEventFilters` method.

.. autoclass:: zuul.trigger.BaseTrigger
   :members:

Current list of triggers are:

.. autoclass:: zuul.driver.gerrit.gerrittrigger.GerritTrigger
   :members:

.. autoclass:: zuul.driver.timer.timertrigger.TimerTrigger
   :members:

.. autoclass:: zuul.driver.zuul.zuultrigger.ZuulTrigger
   :members:
