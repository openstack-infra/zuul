:orphan:

Nodepool - Openstack
====================

Setup
-----

Before starting on this, you need to download your `openrc`
configuration from your OpenStack cloud.  Put it on your server in the
staging user's home directory.  It should be called
``<username>-openrc.sh``.  Once that is done, create a new keypair
that will be installed when instantiating the servers:

.. code-block:: shell

   cd ~
   source <username>-openrc.sh  # this may prompt for password - enter it
   openstack keypair create --public-key nodepool_rsa.pub nodepool

We'll use the private key later wheen configuring Zuul.  In the same
session, configure nodepool to talk to your cloud:

.. code-block:: shell

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

Configuration
-------------

You'll need the following information in order to create the Nodepool
configuration file:

* cloud name / region name - from clouds.yaml
* flavor-name
* image-name - from your cloud

.. code-block:: shell

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
