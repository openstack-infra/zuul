#!/bin/bash

set -eu

cd $(dirname $0)

MYSQL="docker exec zuul-test-mysql mysql  -u root -pinsecure_slave"

docker-compose rm -sf
docker-compose up -d

echo "Waiting for mysql"
timeout 30 bash -c "until ${MYSQL} -e 'show databases'; do sleep 0.5; done"
echo

echo "Setting up permissions for zuul tests"
${MYSQL} -e "GRANT ALL PRIVILEGES ON *.* TO 'openstack_citest'@'%' identified by 'openstack_citest' WITH GRANT OPTION;"
${MYSQL} -u openstack_citest -popenstack_citest -e "SET default_storage_engine=MYISAM; DROP DATABASE IF EXISTS openstack_citest; CREATE DATABASE openstack_citest CHARACTER SET utf8;"

echo "Finished"
