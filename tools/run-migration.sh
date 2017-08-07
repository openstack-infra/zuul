#!/bin/bash
# Copyright (c) 2017 Red Hat, Inc.
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

# Stupid script I'm using to test migration script locally
# Assumes project-config is adjacent to zuul and has the mapping file

BASE_DIR=$(cd $(dirname $0)/../..; pwd)
cd $BASE_DIR/project-config
python3 $BASE_DIR/zuul/zuul/cmd/migrate.py  --mapping=zuul/mapping.yaml \
    zuul/layout.yaml jenkins/jobs nodepool/nodepool.yaml .
