#!/bin/bash -xe

# This script will be run by OpenStack CI before unit tests are run,
# it sets up the test system as needed.
# Developers should setup their test systems in a similar way.

# This setup needs to be run as a user that can run sudo.
TOOLSDIR=$(dirname $0)

# Config Zookeeper to run on tmpfs
sudo service zookeeper stop
DATADIR=$(sed -n -e 's/^dataDir=//p' /etc/zookeeper/conf/zoo.cfg)
sudo mount -t tmpfs -o nodev,nosuid,size=500M none $DATADIR

# Be sure mysql and zookeeper are started.
sudo service mysql start
sudo service postgresql start
sudo service zookeeper start

# The root password for the MySQL database; pass it in via
# MYSQL_ROOT_PW.
DB_ROOT_PW=${MYSQL_ROOT_PW:-insecure_slave}

# This user and its password are used by the tests, if you change it,
# your tests might fail.
DB_USER=openstack_citest
DB_PW=openstack_citest

sudo -H mysqladmin -u root password $DB_ROOT_PW

# It's best practice to remove anonymous users from the database.  If
# a anonymous user exists, then it matches first for connections and
# other connections from that host will not work.
sudo -H mysql -u root -p$DB_ROOT_PW -h localhost -e "
    DELETE FROM mysql.user WHERE User='';
    FLUSH PRIVILEGES;
    GRANT ALL PRIVILEGES ON *.*
        TO '$DB_USER'@'%' identified by '$DB_PW' WITH GRANT OPTION;"

# Now create our database.
mysql -u $DB_USER -p$DB_PW -h 127.0.0.1 -e "
    SET default_storage_engine=MYISAM;
    DROP DATABASE IF EXISTS openstack_citest;
    CREATE DATABASE openstack_citest CHARACTER SET utf8;"

# setup postgres user and database
sudo -u postgres psql -c "CREATE ROLE $DB_USER WITH LOGIN SUPERUSER PASSWORD '$DB_PW';"
sudo -u postgres psql -c "CREATE DATABASE openstack_citest OWNER $DB_USER TEMPLATE template0 ENCODING 'UTF8';"

LSBDISTCODENAME=$(lsb_release -cs)
if [ $LSBDISTCODENAME == 'xenial' ]; then
    # TODO(pabelanger): Move this into bindep after we figure out how to enable our
    # PPA.
    # NOTE(pabelanger): Avoid hitting http://keyserver.ubuntu.com
    sudo apt-key add $TOOLSDIR/018D05F5.gpg
    echo "deb http://ppa.launchpad.net/openstack-ci-core/bubblewrap/ubuntu $LSBDISTCODENAME main" | \
        sudo tee /etc/apt/sources.list.d/openstack-ci-core-ubuntu-bubblewrap-xenial.list
    sudo apt-get update
    sudo apt-get --assume-yes install bubblewrap
fi
