:orphan:

Install Nodepool
================

Initial Setup
-------------

First we'll create the nodepool user and set up some directories it
needs.  We also need to create an SSH key for Zuul to use when it logs
into the nodes that Nodepool provides.

.. code-block:: console

   $ sudo groupadd --system nodepool
   $ sudo useradd --system nodepool --home-dir /var/lib/nodepool --create-home -g nodepool
   $ ssh-keygen -t rsa -b 2048 -f nodepool_rsa  # don't enter a passphrase
   $ sudo mkdir /etc/nodepool/
   $ sudo mkdir /var/log/nodepool
   $ sudo chgrp -R nodepool /var/log/nodepool/
   $ sudo chmod 775 /var/log/nodepool/

Installation
------------

Clone the Nodepool git repository and install it.  The ``bindep``
program is used to determine any additional binary dependencies which
are required.

.. code-block:: console

   $ git clone https://git.zuul-ci.org/nodepool
   $ cd nodepool/
   $ sudo yum -y install $(bindep -b)
   $ sudo pip3 install .

Service File
------------

Nodepool includes a systemd service file for nodepool-launcher in the ``etc``
source directory. To use it, do the following steps.

.. code-block:: console

   $ sudo cp etc/nodepool-launcher.service /etc/systemd/system/nodepool-launcher.service
   $ sudo chmod 0644 /etc/systemd/system/nodepool-launcher.service

If you are installing Nodepool on ``CentOS 7`` and copied the provided service
file in previous step, please follow the steps below to use corresponding
systemd drop-in file so Nodepool service can be managed by systemd.

.. code-block:: console

   $ sudo mkdir /etc/systemd/system/nodepool-launcher.service.d
   $ sudo cp etc/nodepool-launcher.service.d/centos.conf \
        /etc/systemd/system/nodepool-launcher.service.d/centos.conf
   $ sudo chmod 0644 /etc/systemd/system/nodepool-launcher.service.d/centos.conf
