:orphan:

Fedora 27
=========

We're going to be using Fedora 27 on a cloud server for this installation.

Prerequisites
-------------

- Port 9000 must be open and accessible from the internet so that
  Github can communicate with the Zuul web service.

Login to your environment
-------------------------

Since we'll be using a cloud image for Fedora 27, our login user will
be ``fedora`` which will also be the staging user for installation of
Zuul and Nodepool.

To get started, ssh to your machine as the ``fedora`` user::

   ssh fedora@<ip_address>

Environment Setup
-----------------

::

   sudo dnf update -y
   sudo systemctl reboot
   sudo dnf install git redhat-lsb-core python3 python3-pip python3-devel make gcc openssl-devel python-openstackclient -y
   pip3 install --user bindep

Install Zookeeper
-----------------

::

   sudo dnf install zookeeper -y
   sudo cp /etc/zookeeper/zoo_sample.cfg /etc/zookeeper/zoo.cfg
