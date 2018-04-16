Zuul From Scratch
=================

.. note:: This is a work in progress that attempts to walk through all
          of the steps needed to run Zuul on a all-in-one server, and
          demonstrate running against either a GitHub or Gerrit project.

Environment Setup
-----------------

Follow the instructions below, depending on your server type.

  * :doc:`fedora27_setup`

Installation
------------

  * :doc:`nodepool_install`
  * :doc:`zuul_install`

Configuration
-------------

Nodepool
~~~~~~~~

Nodepool can support different backends. Select the configuration for
your installation.

  * :doc:`nodepool_openstack`
  * :doc:`nodepool_static`

Zuul
~~~~

Write the Zuul config file.  Note that this configures Zuul's web
server to listen on all public addresses.  This is so that Zuul may
receive webhook events from GitHub.  You may wish to proxy this or
further restrict public access.

::

   sudo bash -c "cat > /etc/zuul/zuul.conf <<EOF
   [gearman]
   server=127.0.0.1

   [gearman_server]
   start=true

   [executor]
   private_key_file=/home/zuul/.ssh/nodepool_rsa

   [web]
   listen_address=0.0.0.0

   [scheduler]
   tenant_config=/etc/zuul/main.yaml
   EOF"

   sudo bash -c "cat > /etc/zuul/main.yaml <<EOF
   - tenant:
       name: quickstart
   EOF"

Starting Services
-----------------

Your system software management should have installed the Zookeeper service
files for you.

After you have Zuul and Nodepool installed and configured, you can start
all of the services with::

   sudo systemctl daemon-reload

   sudo systemctl start zookeeper.service
   sudo systemctl status zookeeper.service
   sudo systemctl enable zookeeper.service

   sudo systemctl start nodepool-launcher.service
   sudo systemctl status nodepool-launcher.service
   sudo systemctl enable nodepool-launcher.service

   sudo systemctl start zuul-scheduler.service
   sudo systemctl status zuul-scheduler.service
   sudo systemctl enable zuul-scheduler.service
   sudo systemctl start zuul-executor.service
   sudo systemctl status zuul-executor.service
   sudo systemctl enable zuul-executor.service
   sudo systemctl start zuul-web.service
   sudo systemctl status zuul-web.service
   sudo systemctl enable zuul-web.service

Use Zuul Jobs
-------------

Add to ``/etc/zuul/zuul.conf``::

   sudo bash -c "cat >> /etc/zuul/zuul.conf <<EOF

   [connection zuul-git]
   driver=git
   baseurl=https://git.zuul-ci.org/
   EOF"

Restart executor and scheduler::

   sudo systemctl restart zuul-executor.service
   sudo systemctl restart zuul-scheduler.service

Setup Your Repo
---------------

Select your code repository to setup.

  * :doc:`gerrit_setup`
  * :doc:`github_setup`
