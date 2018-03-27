:orphan:

Install Nodepool
================

::

   sudo adduser --system nodepool --home-dir /var/lib/nodepool --create-home
   git clone https://git.zuul-ci.org/nodepool
   cd nodepool/
   sudo dnf -y install $(bindep -b)
   sudo pip3 install .
