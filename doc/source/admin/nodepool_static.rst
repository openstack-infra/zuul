:orphan:

Nodepool - Static
=================

The static driver allows you to use existing compute resources, such as real
hardware or long-lived virtual machines, with nodepool.


Node Requirements
-----------------

Any nodes you setup for nodepool (either real or virtual) must meet
the following requirements:

* Must be reachable by Zuul executors and have SSH access enabled.
* Must have a user that Zuul can use for SSH.
* Must have Python 2 installed for Ansible.

When setting up your nodepool.yaml file, you will need the host keys
for each node for the ``host-key`` value. This can be obtained with
the command::

  $ ssh-keyscan -t ed25519 <HOST>

Nodepool Configuration
----------------------

Below is a sample nodepool.yaml file that sets up static nodes::

  zookeeper-servers:
    - host: localhost

  labels:
    - name: ubuntu-xenial

  providers:
    - name: static-vms
      driver: static
      pools:
        - name: main
          nodes:
            - name: 192.168.1.10
              labels: ubuntu-xenial
              host-key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGXqY02bdYqg1BcIf2x08zs60rS6XhlBSQ4qE47o5gb"
              username: zuul
            - name: 192.168.1.11
              labels: ubuntu-xenial
              host-key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGXqY02bdYqg1BcIf2x08zs60rS6XhlBSQ5sE47o5gc"
              username: zuul

Make sure that ``username``, ``host-key``, IP addresses and label names are
customized for your environment.
