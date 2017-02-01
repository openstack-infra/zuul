# Copyright 2014 Antoine "hashar" Musso
# Copyright 2014 Wikimedia Foundation Inc.
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

import testtools
from zuul.lib.clonemapper import CloneMapper


class TestCloneMapper(testtools.TestCase):

    def test_empty_mapper(self):
        """Given an empty map, the slashes in project names are directory
           separators"""
        cmap = CloneMapper(
            {},
            [
                'project1',
                'plugins/plugin1'
            ])

        self.assertEqual(
            {'project1': '/basepath/project1',
             'plugins/plugin1': '/basepath/plugins/plugin1'},
            cmap.expand('/basepath')
        )

    def test_map_to_a_dot_dir(self):
        """Verify we normalize path, hence '.' refers to the basepath"""
        cmap = CloneMapper(
            [{'name': 'mediawiki/core', 'dest': '.'}],
            ['mediawiki/core'])
        self.assertEqual(
            {'mediawiki/core': '/basepath'},
            cmap.expand('/basepath'))

    def test_map_using_regex(self):
        """One can use regex in maps and use \\1 to forge the directory"""
        cmap = CloneMapper(
            [{'name': 'plugins/(.*)', 'dest': 'project/plugins/\\1'}],
            ['plugins/PluginFirst'])
        self.assertEqual(
            {'plugins/PluginFirst': '/basepath/project/plugins/PluginFirst'},
            cmap.expand('/basepath'))

    def test_map_discarding_regex_group(self):
        cmap = CloneMapper(
            [{'name': 'plugins/(.*)', 'dest': 'project/'}],
            ['plugins/Plugin_1'])
        self.assertEqual(
            {'plugins/Plugin_1': '/basepath/project'},
            cmap.expand('/basepath'))

    def test_cant_dupe_destinations(self):
        """We cant clone multiple projects in the same directory"""
        cmap = CloneMapper(
            [{'name': 'plugins/(.*)', 'dest': 'catchall/'}],
            ['plugins/plugin1', 'plugins/plugin2']
        )
        self.assertRaises(Exception, cmap.expand, '/basepath')

    def test_map_with_dot_and_regex(self):
        """Combining relative path and regex"""
        cmap = CloneMapper(
            [{'name': 'plugins/(.*)', 'dest': './\\1'}],
            ['plugins/PluginInBasePath'])
        self.assertEqual(
            {'plugins/PluginInBasePath': '/basepath/PluginInBasePath'},
            cmap.expand('/basepath'))
