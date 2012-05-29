#!/usr/bin/env python
# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from setuptools import find_packages
from setuptools.command.sdist import sdist
from setuptools import setup
import subprocess

setup(name='zuul',
      version='1.0',
      description="Trunk gating system",
      license='Apache License (2.0)',
      author='Hewlett-Packard Development Company, L.P.',
      author_email='openstack@lists.launchpad.net',
      url='http://launchpad.net/zuul',
      scripts=['zuul-server'],
      include_package_data=True,
      zip_safe=False,
      packages=find_packages(),
      )
