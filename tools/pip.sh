#!/bin/bash
# Copyright 2018 Red Hat, Inc.
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

set -e

# This script checks if yarn is installed in the current path. If it is not,
# it will use nodeenv to install node, npm and yarn.
# Finally, it will install pip things.
if [[ ! $(command -v yarn) ]]
then
    pip install nodeenv
    # Initialize nodeenv and tell it to re-use the currently active virtualenv
    # TODO(jeblair): remove node version pin.  upath 1.0.4 objects to node >9.
    nodeenv --python-virtualenv -n 8.11.1
    # Use -g because inside of the virtualenv '-g' means 'install into the'
    # virtualenv - as opposed to installing into the local node_modules.
    # Avoid writing a package-lock.json file since we don't use it.
    # Avoid writing yarn into package.json.
    npm install -g --no-package-lock --no-save yarn
fi
if [[ ! -f zuul/web/static/status.html ]]
then
    pushd web/
        yarn install
        yarn build
    popd
fi
pip install $*

# Check if we're installing zuul. If so install the managed ansible as well.
if echo "$*" | grep -vq requirements.txt; then
    zuul-manage-ansible -v
fi
