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

import setuptools
from zuul.openstack.common import setup
from zuul.version import version_info as version

requires = setup.parse_requirements()
test_requires = setup.parse_requirements(['tools/test-requires'])
depend_links = setup.parse_dependency_links()


setuptools.setup(
    name='zuul',
    version=version.canonical_version_string(always=True),
    author='Hewlett-Packard Development Company, L.P.',
    author_email='openstack@lists.launchpad.net',
    description='Trunk gating system',
    license='Apache License, Version 2.0',
    url='http://launchpad.net/zuul',
    packages=setuptools.find_packages(exclude=['tests', 'tests.*']),
    include_package_data=True,
    cmdclass=setup.get_cmdclass(),
    install_requires=requires,
    dependency_links=depend_links,
    zip_safe=False,
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python'
    ],
    entry_points={
        'console_scripts': [
            'zuul-server=zuul.cmd.server:main',
        ],
    }
)
