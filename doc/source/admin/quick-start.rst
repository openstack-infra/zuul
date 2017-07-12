Quick Start Guide
=================

This provides a very simple overview of Zuul.  It is recommended to
read the following sections for more details.

Install Zuul
------------

You can get zuul from pypi via::

    pip install zuul

Zuul Components
---------------

Zuul provides the following components:

    - **zuul-scheduler**: The main Zuul process. Handles receiving
      events, executing jobs, collecting results and posting reports.
      Coordinates the work of the other components.

    - **zuul-merger**: Scale-out component that performs git merge
      operations.  Zuul performs a large number of git operations in
      the course of its work.  Adding merger processes can help speed
      Zuul's processing.  This component is optional (zero or more of
      these can be run).

    - **zuul-executor**: Scale-out component for executing jobs.  At
      least one of these is required.  Depending on system
      configuration, you can expect a single executor to handle up to
      about 100 simultaneous jobs.  Can handle the functions of a
      merger if dedicated mergers are not provided.  One or more of
      these must be run.

    - **zuul-web**: A web server that currently provides websocket access to
      live-streaming of logs.

    - **gearman**: optional builtin gearman daemon provided by zuul-scheduler

External components:

    - **gearman**: A gearman daemon if the built-in daemon is not used.

    - **zookeeper**: A zookeeper cluster (or single host) for
      communicating with Nodepool.

    - **nodepool**: Provides nodes for Zuul to use when executing jobs.


Zuul Setup
----------

At minimum you need to provide **zuul.conf** and **main.yaml** placed
in **/etc/zuul/**.  The following example uses the builtin gearman
service in Zuul, and a connection to Gerrit.

**zuul.conf**::

    [scheduler]
    tenant_config=/etc/zuul/main.yaml

    [gearman_server]
    start=true

    [gearman]
    server=127.0.0.1

    [connection gerrit]
    driver=gerrit
    server=git.example.com
    port=29418
    baseurl=https://git.example.com/gerrit/
    user=zuul
    sshkey=/home/zuul/.ssh/id_rsa

See :ref:`components` and :ref:`connections` for more details.

The following tells Zuul to read its configuration from and operate on
the *example-project* project:

**main.yaml**::

    - tenant:
        name: example-tenant
        source:
          gerrit:
            untrusted-projects:
              - example-project

Starting Zuul
-------------

You can run any zuul process with the **-d** option to make it not
daemonize. It's a good idea at first to confirm there's no issues with
your configuration.

To start, simply run::

    zuul-scheduler

Once run you should have two zuul-scheduler processes (if using the
built-in gearman server, or one process otherwise).

Before Zuul can run any jobs, it needs to load its configuration, most
of which is in the git repositories that Zuul operates on.  Start an
executor to allow zuul to do that::

    zuul-executor

Zuul should now be able to read its configuration from the configured
repo and process any jobs defined therein.

Troubleshooting
---------------

You can use telnet to connect to gearman to check which Zuul
components are online::

    telnet <gearman_ip> 4730

Useful commands are **workers** and **status** which you can run by just
typing those commands once connected to gearman.
