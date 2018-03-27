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

   sudo chmod 0644 /etc/systemd/system/zuul-scheduler.service
   sudo chmod 0644 /etc/systemd/system/zuul-executor.service
   sudo chmod 0644 /etc/systemd/system/zuul-web.service

Starting Services
~~~~~~~~~~~~~~~~~

After you have Zuul and Nodepool installed and configured, you can start
those services with::

   sudo systemctl daemon-reload

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
