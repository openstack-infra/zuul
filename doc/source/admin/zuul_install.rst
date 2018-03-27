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
