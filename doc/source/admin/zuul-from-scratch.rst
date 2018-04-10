Zuul From Scratch
=================

.. note:: This is a work in progress that attempts to walk through all
          of the steps needed to run Zuul on a cloud server against
          GitHub projects.

Environment Setup
-----------------

We're going to be using Fedora 27 on a cloud server for this
installation.

Prerequisites
~~~~~~~~~~~~~

- Port 9000 must be open and accessible from the internet so that 
  Github can communicate with the Zuul web service.
- You need an OpenStack cloud that serves as your node pool.
  For experimentation, DevStack is fine.

Login to your environment
~~~~~~~~~~~~~~~~~~~~~~~~~

Since we'll be using a cloud image for Fedora 27, our login user will
be ``fedora`` which will also be the staging user for installation of
Zuul and Nodepool.

To get started, ssh to your machine as the ``fedora`` user::

   ssh fedora@<ip_address>

Environment Setup
~~~~~~~~~~~~~~~~~

::

   sudo dnf update -y
   sudo systemctl reboot
   sudo dnf install git redhat-lsb-core python3 python3-pip python3-devel make gcc openssl-devel python-openstackclient -y
   pip3 install --user bindep

Zuul and Nodepool Installation
------------------------------

Install Zookeeper
~~~~~~~~~~~~~~~~~

::

   sudo dnf install zookeeper -y

Install Nodepool
~~~~~~~~~~~~~~~~

::

   sudo adduser --system nodepool --home-dir /var/lib/nodepool --create-home
   git clone https://git.zuul-ci.org/nodepool
   cd nodepool/
   sudo dnf -y install $(bindep -b)
   sudo pip3 install .

Install Zuul
~~~~~~~~~~~~

::

   sudo adduser --system zuul --home-dir /var/lib/zuul --create-home
   git clone https://git.zuul-ci.org/zuul
   cd zuul/
   sudo dnf install $(bindep -b) -y
   sudo pip3 install .

Setup
-----

Zookeeper Setup
~~~~~~~~~~~~~~~

.. TODO recommended reading for zk clustering setup

::

   sudo bash -c 'echo "1" > /etc/zookeeper/myid'
   sudo bash -c 'echo "tickTime=2000
   dataDir=/var/lib/zookeeper
   clientPort=2181" > /etc/zookeeper/zoo.cfg'

Nodepool Setup
~~~~~~~~~~~~~~

Before starting on this, you need to download your `openrc`
configuration from your OpenStack cloud.  Put it on your server in the
fedora user's home directory.  It should be called
``<username>-openrc.sh``.  Once that is done, create a new keypair
that will be installed when instantiating the servers::

   cd ~
   source <username>-openrc.sh  # this may prompt for password - enter it
   ssh-keygen -t rsa -b 2048 -f nodepool_rsa  # don't enter a passphrase
   openstack keypair create --public-key nodepool_rsa.pub nodepool

We'll use the private key later wheen configuring Zuul.  In the same
session, configure nodepool to talk to your cloud::

   umask 0066
   sudo mkdir -p ~nodepool/.config/openstack
   cat > clouds.yaml <<EOF
   clouds:
     mycloud:
       auth:
         username: $OS_USERNAME
         password: $OS_PASSWORD
         project_name: ${OS_PROJECT_NAME:-$OS_TENANT_NAME}
         auth_url: $OS_AUTH_URL
       region_name: $OS_REGION_NAME
   EOF
   sudo mv clouds.yaml ~nodepool/.config/openstack/
   sudo chown -R nodepool.nodepool ~nodepool/.config
   umask 0002

Once you've written out the file, double check all the required fields
have been filled out.

::

   sudo mkdir /etc/nodepool/
   sudo mkdir /var/log/nodepool
   sudo chgrp -R nodepool /var/log/nodepool/
   sudo chmod 775 /var/log/nodepool/

Nodepool Configuration
~~~~~~~~~~~~~~~~~~~~~~

Inputs needed for this file:

* cloud name / region name - from clouds.yaml
* flavor-name
* image-name - from your cloud

::

   sudo bash -c "cat >/etc/nodepool/nodepool.yaml <<EOF
   zookeeper-servers:
     - host: localhost
       port: 2181

   providers:
     - name: myprovider # this is a nodepool identifier for this cloud provider (cloud+region combo)
       region-name: regionOne  # this needs to match the region name in clouds.yaml but is only needed if there is more than one region
       cloud: mycloud  # This needs to match the name in clouds.yaml
       cloud-images:
         - name: centos-7   # Defines a cloud-image for nodepool
           image-name: CentOS-7-x86_64-GenericCloud-1706  # name of image from cloud
           username: centos  # The user Zuul should log in as
       pools:
         - name: main
           max-servers: 4  # nodepool will never create more than this many servers
           labels:
             - name: centos-7-small  # defines label that will be used to get one of these in a job
               flavor-name: 'm1.small'  # name of flavor from cloud
               cloud-image: centos-7  # matches name from cloud-images
               key-name: nodepool # name of the keypair to use for authentication

   labels:
     - name: centos-7-small # defines label that will be used in jobs
       min-ready: 2  # nodepool will always keep this many booted and ready to go
   EOF"

.. warning::

   `min-ready:2` may incur costs in your cloud provider


Zuul Setup
~~~~~~~~~~

::

   sudo mkdir /etc/zuul/
   sudo mkdir /var/log/zuul/
   sudo chown zuul.zuul /var/log/zuul/
   sudo mkdir /var/lib/zuul/.ssh
   sudo chmod 0700 /var/lib/zuul/.ssh
   sudo mv nodepool_rsa /var/lib/zuul/.ssh
   sudo chown -R zuul.zuul /var/lib/zuul/.ssh

Zuul Configuration
~~~~~~~~~~~~~~~~~~

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

Service Management
------------------

Zookeeper Service Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   sudo systemctl start zookeeper.service

::

   sudo systemctl status zookeeper.service
   ● zookeeper.service - Apache ZooKeeper
      Loaded: loaded (/usr/lib/systemd/system/zookeeper.service; disabled; vendor preset: disabled)
      Active: active (running) since Wed 2018-01-03 14:53:47 UTC; 5s ago
     Process: 4153 ExecStart=/usr/bin/zkServer.sh start zoo.cfg (code=exited, status=0/SUCCESS)
    Main PID: 4160 (java)
       Tasks: 17 (limit: 4915)
      CGroup: /system.slice/zookeeper.service
              └─4160 java -Dzookeeper.log.dir=/var/log/zookeeper -Dzookeeper.root.logger=INFO,CONSOLE -cp /usr/share/java/

::

   sudo systemctl enable zookeeper.service


Nodepool Service Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   sudo bash -c "cat > /etc/systemd/system/nodepool-launcher.service <<EOF
   [Unit]
   Description=Nodepool Launcher Service
   After=syslog.target network.target

   [Service]
   Type=simple
   # Options to pass to nodepool-launcher.
   Group=nodepool
   User=nodepool
   RuntimeDirectory=nodepool
   ExecStart=/usr/local/bin/nodepool-launcher

   [Install]
   WantedBy=multi-user.target
   EOF"

   sudo chmod 0644 /etc/systemd/system/nodepool-launcher.service
   sudo systemctl daemon-reload
   sudo systemctl start nodepool-launcher.service
   sudo systemctl status nodepool-launcher.service
   sudo systemctl enable nodepool-launcher.service

Zuul Service Management
~~~~~~~~~~~~~~~~~~~~~~~
::

   sudo bash -c "cat > /etc/systemd/system/zuul-scheduler.service <<EOF
   [Unit]
   Description=Zuul Scheduler Service
   After=syslog.target network.target

   [Service]
   Type=simple
   Group=zuul
   User=zuul
   RuntimeDirectory=zuul
   ExecStart=/usr/local/bin/zuul-scheduler
   ExecStop=/usr/local/bin/zuul-scheduler stop

   [Install]
   WantedBy=multi-user.target
   EOF"

   sudo bash -c "cat > /etc/systemd/system/zuul-executor.service <<EOF
   [Unit]
   Description=Zuul Executor Service
   After=syslog.target network.target

   [Service]
   Type=simple
   Group=zuul
   User=zuul
   RuntimeDirectory=zuul
   ExecStart=/usr/local/bin/zuul-executor
   ExecStop=/usr/local/bin/zuul-executor stop

   [Install]
   WantedBy=multi-user.target
   EOF"

   sudo bash -c "cat > /etc/systemd/system/zuul-web.service <<EOF
   [Unit]
   Description=Zuul Web Service
   After=syslog.target network.target

   [Service]
   Type=simple
   Group=zuul
   User=zuul
   RuntimeDirectory=zuul
   ExecStart=/usr/local/bin/zuul-web
   ExecStop=/usr/local/bin/zuul-web stop

   [Install]
   WantedBy=multi-user.target
   EOF"

   sudo systemctl daemon-reload
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

Configure GitHub
----------------

You'll need an organization in Github for this, so create one if you
haven't already.  In this example we will use `my-org`.

.. NOTE Duplicate content here and in drivers/github.rst.  Keep them
   in sync.

Create a `GitHub application
<https://developer.github.com/apps/building-integrations/setting-up-and-registering-github-apps/registering-github-apps/>`_:

* Go to your organization settings page to create the application, e.g.:
  https://github.com/organizations/my-org/settings/apps/new
* Set GitHub App name to "my-org-zuul"
* Set Setup URL to your setup documentation, when users install the application
  they are redirected to this url
* Set Webhook URL to
  ``http://<IP ADDRESS>:9000/api/connection/github/payload``.
* Create a Webhook secret, and record it for later use
* Set permissions:

  * Commit statuses: Read & Write
  * Issues: Read & Write
  * Pull requests: Read & Write
  * Repository contents: Read & Write (write to let zuul merge change)
  * Repository administration: Read

* Set events subscription:

  * Label
  * Status
  * Issue comment
  * Issues
  * Pull request
  * Pull request review
  * Pull request review comment
  * Commit comment
  * Create
  * Push
  * Release

* Set Where can this GitHub App be installed to "Any account"
* Create the App
* Generate a Private key in the app settings page and save the file
  for later

.. TODO See if we can script this using GitHub API

Go back to the `General` settings page for the app,
https://github.com/organizations/my-org/settings/apps/my-org-zuul
and look for the app `ID` number, under the `About` section.

Edit ``/etc/zuul/zuul.conf`` to add the following::

  [connection github]
  driver=github
  app_id=<APP ID NUMBER>
  app_key=/etc/zuul/github.pem
  webhook_token=<WEBHOOK SECRET>

Upload the private key which was generated earlier, and save it in
``/etc/zuul/github.pem``.

Restart all of Zuul::

  sudo systemctl restart zuul-executor.service
  sudo systemctl restart zuul-web.service
  sudo systemctl restart zuul-scheduler.service

Go to the `Advanced` tab for the app in GitHub,
https://github.com/organizations/my-org/settings/apps/my-org-zuul/advanced,
and look for the initial ping from the app.  It probably wasn't
delivered since Zuul wasn't configured at the time, so click
``Resend`` and verify that it is delivered now that Zuul is
configured.

Create two new repositories in your org.  One will hold the
configuration for this tenant in Zuul, the other should be a normal
project repo to use for testing.  We'll call them `zuul-test-config`
and `zuul-test`, respectively.

Visit the public app page on GitHub,
https://github.com/apps/my-org-zuul, and install the app into your org.

Edit ``/etc/zuul/main.yaml`` so that it looks like this::

   - tenant:
       name: quickstart
       source:
         zuul-git:
           config-projects:
             - zuul-base-jobs
           untrusted-projects:
             - zuul-jobs
         github:
           config-projects:
             - my-org/zuul-test-config
           untrusted-projects:
             - my-org/zuul-test

The first section, under 'zuul-git' imports the "standard library" of
Zuul jobs, a collection of jobs that can be used by any Zuul
installation.

The second section is your GitHub configuration.

After updating the file, restart the Zuul scheduler::

  sudo systemctl restart zuul-scheduler.service

Add an initial pipeline configuration to the `zuul-test-config`
repository.  Inside that project, create a ``zuul.yaml`` file with the
following contents::

   - pipeline:
       name: check
       description: |
         Newly opened pull requests enter this pipeline to receive an
         initial verification
       manager: independent
       trigger:
         github:
           - event: pull_request
             action:
               - opened
               - changed
               - reopened
           - event: pull_request
             action: comment
             comment: (?i)^\s*recheck\s*$
       start:
         github:
           status: pending
           comment: false
       success:
         github:
           status: 'success'
       failure:
         github:
           status: 'failure'

Merge that commit into the repository.

In the `zuul-test` project, create a `.zuul.yaml` file with the
following contents::

   - project:
       check:
         jobs:
           - noop

Open a new pull request with that commit against the `zuul-test`
project and verify that Zuul reports a successful run of the `noop`
job.
