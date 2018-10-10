:orphan:

CentOS 7
=========

We're going to be using CentOS 7 on a cloud server for this installation.

Prerequisites
-------------

- Port 9000 must be open and accessible from the Internet so that
  GitHub can communicate with the Zuul web service.

Login to your environment
-------------------------

Since we'll be using a cloud image for CentOS 7, our login user will
be ``centos`` which will also be the staging user for installation of
Zuul and Nodepool.

To get started, ssh to your machine as the ``centos`` user.

.. code-block:: shell

   ssh centos@<ip_address>

Environment Setup
-----------------

Certain packages needed for Zuul and Nodepool are not available in upstream
CentOS 7 repositories so additional repositories need to be enabled.

The repositories and the packages installed from those are listed below.

* ius-release: python35u, python35u-pip, python35u-devel
* bigtop: zookeeper

First, make sure the system packages are up to date, and then install
some packages which will be required later.  Most of Zuul's binary
dependencies are handled by the bindep program, but a few additional
dependencies are needed to install bindep, and for other commands
which we will use in these instructions.

.. code-block:: shell

   sudo yum update -y
   sudo systemctl reboot
   sudo yum install -y https://centos7.iuscommunity.org/ius-release.rpm
   sudo yum install -y git python35u python35u-pip python35u-devel java-1.8.0-openjdk
   sudo alternatives --install /usr/bin/python3 python3 /usr/bin/python3.5 10
   sudo alternatives --install /usr/bin/pip3 pip3 /usr/bin/pip3.5 10
   sudo pip3 install python-openstackclient bindep

Install Zookeeper
-----------------

Nodepool uses Zookeeper to keep track of information about the
resources it manages, and it's also how Zuul makes requests to
Nodepool for nodes.

.. code-block:: console

   sudo bash -c "cat << EOF > /etc/yum.repos.d/bigtop.repo
   [bigtop]
   name=Bigtop
   enabled=1
   gpgcheck=1
   type=NONE
   baseurl=http://repos.bigtop.apache.org/releases/1.2.1/centos/7/x86_64
   gpgkey=https://dist.apache.org/repos/dist/release/bigtop/KEYS
   EOF"
   sudo yum install -y zookeeper zookeeper-server
   sudo systemctl start zookeeper-server.service
   sudo systemctl status zookeeper-server.service
   sudo systemctl enable zookeeper-server.service
