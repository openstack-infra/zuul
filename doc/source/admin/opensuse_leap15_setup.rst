:orphan:

openSUSE Leap 15
================

We're going to be using openSUSE Leap 15 for this installation.

Prerequisites
-------------

If you are using Zuul with GitHub,

- Port 9000 must be open and accessible from the Internet so that
  GitHub can communicate with the Zuul web service.

Environment Setup
-----------------

First, make sure the system packages are up to date, and then install
some packages which will be required later.  Most of Zuul's binary
dependencies are handled by the bindep program, but a few additional
dependencies are needed to install bindep, and for other commands
which we will use in these instructions.

.. code-block:: shell

   sudo zypper install -y git python3-pip

Then install bindep

.. code-block:: shell

   pip3 install --user bindep
   # Add it to your path
   PATH=~/.local/bin:$PATH

Install Zookeeper
-----------------

Nodepool uses Zookeeper to keep track of information about the
resources it manages, and it's also how Zuul makes requests to
Nodepool for nodes.

You should follow the `official deployment instructions for zookeeper
<https://zookeeper.apache.org/doc/current/zookeeperAdmin.html>`_,
but to get started quickly, just download, unpack and run.

To download follow the directions on `Zookeeper's releases page
<https://zookeeper.apache.org/releases.html>`_ to grab the latest
release of zookeeper. Then:

.. code-block:: shell

   sudo zypper install -y java-1_8_0-openjdk
   tar -xzf zookeeper-3.4.12.tar.gz # Tarball downloaded from Zookeeper
   cp zookeeper-3.4.12/conf/zoo_sample.cfg zookeeper-3.4.12/conf/zoo.cfg
   ./zookeeper-3.4.12/bin/zkServer.sh start

.. note:: Don't forget to follow `Apache's checksum instructions
          <https://www.apache.org/dyn/closer.cgi#verify>`_ before
          extracting.
