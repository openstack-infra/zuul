Quick Start Guide
=================

System Requirements
-------------------

For most deployments zuul only needs 1-2GB. OpenStack uses a 30GB setup.

Install Zuul
------------

You can get zuul from pypi via::

    pip install zuul

Zuul Components
---------------

Zuul provides the following components:

    - **zuul-server**: scheduler daemon which communicates with Gerrit and
      Gearman. Handles receiving events, launching jobs, collecting results
      and postingreports.
    - **zuul-merger**: speculative-merger which communicates with Gearman.
      Prepares Git repositories for jobs to test against. This additionally
      requires a web server hosting the Git repositories which can be cloned
      by the jobs.
    - **zuul-cloner**: client side script used to setup job workspace. It is
      used to clone the repositories prepared by the zuul-merger described
      previously.
    - **gearmand**: optional builtin gearman daemon provided by zuul-server

External components:

    - Jenkins Gearman plugin: Used by Jenkins to connect to Gearman

Zuul Communication
------------------

All the Zuul components communicate with each other using Gearman. As well as
the following communication channels:

zuul-server:

    - Gerrit
    - Gearman Daemon

zuul-merger:

    - Gerrit
    - Gearman Daemon

zuul-cloner:

    - http hosted zuul-merger git repos

Jenkins:

    - Gearman Daemon via Jenkins Gearman Plugin

Zuul Setup
----------

At minimum we need to provide **zuul.conf** and **layout.yaml** and placed
in /etc/zuul/ directory. You will also need a zuul user and ssh key for the
zuul user in Gerrit. The following example uses the builtin gearmand service
in zuul.

**zuul.conf**::

    [zuul]
    layout_config=/etc/zuul/layout.yaml

    [merger]
    git_dir=/git
    zuul_url=http://zuul.example.com/p

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

See :doc:`zuul` for more details.

The following sets up a basic timer triggered job using zuul.

**layout.yaml**::

    pipelines:
      - name: periodic
        source: gerrit
        manager: IndependentPipelineManager
        trigger:
          timer:
            - time: '0 * * * *'

    projects:
      - name: aproject
        periodic:
          - aproject-periodic-build

Starting Zuul
-------------

You can run zuul-server with the **-d** option to make it not daemonize. It's
a good idea at first to confirm there's no issues with your configuration.

Simply run::

    zuul-server

Once run you should have 2 zuul-server processes::

    zuul     12102     1  0 Jan21 ?        00:15:45 /home/zuul/zuulvenv/bin/python /home/zuul/zuulvenv/bin/zuul-server -d
    zuul     12107 12102  0 Jan21 ?        00:00:01 /home/zuul/zuulvenv/bin/python /home/zuul/zuulvenv/bin/zuul-server -d

Note: In this example zuul was installed in a virtualenv.

The 2nd zuul-server process is gearmand running if you are using the builtin
gearmand server, otherwise there will only be 1 process.

Zuul won't actually process your Job queue however unless you also have a
zuul-merger process running.

Simply run::

    zuul-merger

Zuul should now be able to process your periodic job as configured above once
the Jenkins side of things is configured.

Jenkins Setup
-------------

Install the Jenkins Gearman Plugin via Jenkins Plugin management interface.
Then naviage to **Manage > Configuration > Gearman** and setup the Jenkins
server hostname/ip and port to connect to gearman.

At this point gearman should be running your Jenkins jobs.

Troubleshooting
---------------

Checking Gearman function registration (jobs). You can use telnet to connect
to gearman to check that Jenkins is registering your configured jobs in
gearman::

    telnet <gearman_ip> 4730

Useful commands are **workers** and **status** which you can run by just
typing those commands once connected to gearman. Every job in your Jenkins
master must appear when you run **workers** for Zuul to be able to run jobs
against your Jenkins instance.
