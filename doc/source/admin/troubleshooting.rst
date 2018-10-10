Troubleshooting
---------------

You can use telnet to connect to gearman to check which Zuul
components are online::

    telnet <gearman_ip> 4730

Useful commands are ``workers`` and ``status`` which you can run by just
typing those commands once connected to gearman.
