#!/bin/bash -xe

/usr/zuul-env/bin/zuul-cloner --cache-dir /opt/git git://git.openstack.org \
    openstack-infra/nodepool

cd openstack-infra/nodepool
/usr/local/jenkins/slave_scripts/install-distro-packages.sh
sudo pip install .

cd $WORKSPACE

cd openstack-infra/zuul
/usr/local/jenkins/slave_scripts/install-distro-packages.sh
sudo pip install .

cd $WORKSPACE

bash -xe openstack-infra/nodepool/tools/zuul-nodepool-integration/start.sh

# TODO(jeblair): something useful and save logs
sleep 30
cat /tmp/nodepool/log/nodepool-builder.log
cat /tmp/nodepool/log/nodepool-launcher.log
