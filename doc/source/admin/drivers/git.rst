:title: Git Driver

Git
===

This driver can be used to load Zuul configuration from public Git repositories,
for instance from ``openstack-infra/zuul-jobs`` that is suitable for use by
any Zuul system. It can also be used to trigger jobs from ``ref-updated`` events
in a pipeline.

Connection Configuration
------------------------

The supported options in ``zuul.conf`` connections are:

.. attr:: <git connection>

   .. attr:: driver
      :required:

      .. value:: git

         The connection must set ``driver=git`` for Git connections.

   .. attr:: baseurl

      Path to the base Git URL. Git repos name will be appended to it.

   .. attr:: poll_delay
      :default: 7200

      The delay in seconds of the Git repositories polling loop.

Trigger Configuration
---------------------

.. attr:: pipeline.trigger.<git source>

   The dictionary passed to the Git pipeline ``trigger`` attribute
   supports the following attributes:

   .. attr:: event
      :required:

      Only ``ref-updated`` is supported.

   .. attr:: ref

      On ref-updated events, a ref such as ``refs/heads/master`` or
      ``^refs/tags/.*$``. This field is treated as a regular expression,
      and multiple refs may be listed.

   .. attr:: ignore-deletes
      :default: true

      When a ref is deleted, a ref-updated event is emitted with a
      newrev of all zeros specified. The ``ignore-deletes`` field is a
      boolean value that describes whether or not these newrevs
      trigger ref-updated events.
