Troubleshooting
---------------

Some advanced troubleshooting options are provided below.  These are
generally very low-level and are not normally required.

.. _debug_gearman:

Gearman Jobs
============

Connecting to Gearman can allow you see if any Zuul components appear
to not be accepting requests correctly.

For unencrypted Gearman connections, you can use telnet to connect to
and check which Zuul components are online::

    telnet <gearman_ip> 4730

For encrypted connections, you will need to provide suitable keys,
e.g::

    openssl s_client -connect localhost:4730 -cert /etc/zuul/ssl/client.pem  -key /etc/zuul/ssl/client.key

Commands available are discussed in the Gearman `administrative
protocol <http://gearman.org/protocol>`__.  Useful commands are
``workers`` and ``status`` which you can run by just typing those
commands once connected to gearman.

For ``status`` you will see output for internal Zuul functions in the
form ``FUNCTION\tTOTAL\tRUNNING\tAVAILABLE_WORKERS``::

  ...
  executor:resume:ze06.openstack.org	0	0	1
  zuul:config_errors_list	0	0	1
  zuul:status_get	0	0	1
  executor:stop:ze11.openstack.org	0	0	1
  zuul:job_list	0	0	1
  zuul:tenant_sql_connection	0	0	1
  executor:resume:ze09.openstack.org	0	0	1
  ...
