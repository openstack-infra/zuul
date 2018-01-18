#!/bin/bash
# Copyright 2017 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

ZUUL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
ARA_DIR=$(dirname $(python3 -c 'import ara ; print(ara.__file__)'))
WORK_DIR=$PWD/test-logs-output

mkdir -p $WORK_DIR

if [ -z $1 ] ; then
    INVENTORY=$WORK_DIR/hosts.yaml
    cat >$INVENTORY <<EOF
all:
  hosts:
    controller:
      ansible_host: localhost
    node1:
      ansible_host: localhost
    node2:
      ansible_host: localhost
node:
  hosts:
    node1: null
    node2: null
EOF
else
    INVENTORY=$(realpath $1)
fi

cat >$WORK_DIR/ansible.cfg <<EOF
[defaults]
inventory = $INVENTORY
gathering = smart
gather_subset = !all
fact_caching = jsonfile
fact_caching_connection = ~/.cache/facts
lookup_plugins = $ZUUL_DIR/zuul/ansible/lookup
callback_plugins = $ZUUL_DIR/zuul/ansible/callback:$ARA_DIR/plugins/callbacks
module_utils = $ZUUL_DIR/zuul/ansible/module_utils
stdout_callback = zuul_stream
library = $ZUUL_DIR/zuul/ansible/library
retry_files_enabled = False
EOF

cd $WORK_DIR
python3 $ZUUL_DIR/zuul/ansible/logconfig.py
export ZUUL_JOB_LOG_CONFIG=$WORK_DIR/logging.json
export ARA_DIR=$WORK_DIR/.ara
export ARA_LOG_CONFIG=$ZUUL_JOB_LOG_CONFIG
rm -rf $ARA_DIR
ansible-playbook $ZUUL_DIR/playbooks/zuul-stream/fixtures/test-stream.yaml
ansible-playbook $ZUUL_DIR/playbooks/zuul-stream/fixtures/test-stream-failure.yaml
echo "Logs are in $WORK_DIR"
