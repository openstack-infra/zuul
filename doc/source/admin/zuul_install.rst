:orphan:

Install Zuul
============

::

   sudo adduser --system zuul --home-dir /var/lib/zuul --create-home
   git clone https://git.zuul-ci.org/zuul
   cd zuul/
   sudo dnf install $(bindep -b) -y
   sudo pip3 install .

Initial Setup
-------------

::

   sudo mkdir /etc/zuul/
   sudo mkdir /var/log/zuul/
   sudo chown zuul.zuul /var/log/zuul/
   sudo mkdir /var/lib/zuul/.ssh
   sudo chmod 0700 /var/lib/zuul/.ssh
   sudo mv nodepool_rsa /var/lib/zuul/.ssh
   sudo chown -R zuul.zuul /var/lib/zuul/.ssh

Service Files
-------------

Zuul includes some systemd service files for Zuul in the ``etc`` source
directory. To use them, do the following steps::

  $ sudo cp etc/zuul-scheduler.service /etc/systemd/system/zuul-scheduler.service
  $ sudo cp etc/zuul-executor.service /etc/systemd/system/zuul-executor.service
  $ sudo cp etc/zuul-web.service /etc/systemd/system/zuul-web.service
  $ sudo chmod 0644 /etc/systemd/system/zuul-scheduler.service
  $ sudo chmod 0644 /etc/systemd/system/zuul-executor.service
  $ sudo chmod 0644 /etc/systemd/system/zuul-web.service
