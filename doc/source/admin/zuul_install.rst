:orphan:

Install Zuul
============

Initial Setup
-------------

First we'll create the zuul user and set up some directories it needs.
We'll also install the SSH private key that we previously created
during the Nodepool setup.

.. code-block:: console

   $ sudo groupadd --system zuul
   $ sudo useradd --system zuul --home-dir /var/lib/zuul --create-home -g zuul
   $ sudo mkdir /etc/zuul/
   $ sudo mkdir /var/log/zuul/
   $ sudo chown zuul:zuul /var/log/zuul/
   $ sudo mkdir /var/lib/zuul/.ssh
   $ sudo chmod 0700 /var/lib/zuul/.ssh
   $ sudo mv nodepool_rsa /var/lib/zuul/.ssh
   $ sudo chown -R zuul:zuul /var/lib/zuul/.ssh

Installation
------------

Clone the Zuul git repository and install it.  The ``bindep`` program
is used to determine any additional binary dependencies which are
required.

.. code-block:: console

   # All:
   $ git clone https://git.zuul-ci.org/zuul
   $ pushd zuul/

   # For Fedora and CentOS:
   $ sudo yum -y install $(bindep -b compile)

   # For openSUSE:
   $ zypper install -y $(bindep -b compile)

   # All:
   $ sudo pip3 install .
   $ sudo zuul-manage-ansible
   $ popd

Service Files
-------------

Zuul includes systemd service files for Zuul services in the ``etc`` source
directory. To use them, do the following steps.

.. code-block:: console

   $ sudo cp etc/zuul-scheduler.service /etc/systemd/system/zuul-scheduler.service
   $ sudo cp etc/zuul-executor.service /etc/systemd/system/zuul-executor.service
   $ sudo cp etc/zuul-web.service /etc/systemd/system/zuul-web.service
   $ sudo chmod 0644 /etc/systemd/system/zuul-scheduler.service
   $ sudo chmod 0644 /etc/systemd/system/zuul-executor.service
   $ sudo chmod 0644 /etc/systemd/system/zuul-web.service

If you are installing Zuul on ``CentOS 7`` and copied the provided service
files in previous step, please follow the steps below to use corresponding
systemd drop-in files so Zuul services can be managed by systemd.

.. code-block:: console

   $ sudo mkdir /etc/systemd/system/zuul-scheduler.service.d
   $ sudo cp etc/zuul-scheduler.service.d/centos.conf \
       /etc/systemd/system/zuul-scheduler.service.d/centos.conf
   $ sudo chmod 0644 /etc/systemd/system/zuul-scheduler.service.d/centos.conf
   $ sudo mkdir /etc/systemd/system/zuul-executor.service.d
   $ sudo cp etc/zuul-executor.service.d/centos.conf \
       /etc/systemd/system/zuul-executor.service.d/centos.conf
   $ sudo chmod 0644 /etc/systemd/system/zuul-executor.service.d/centos.conf
   $ sudo mkdir /etc/systemd/system/zuul-web.service.d
   $ sudo cp etc/zuul-web.service.d/centos.conf \
       /etc/systemd/system/zuul-web.service.d/centos.conf
   $ sudo chmod 0644 /etc/systemd/system/zuul-web.service.d/centos.conf
