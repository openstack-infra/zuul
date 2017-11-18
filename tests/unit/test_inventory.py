#!/usr/bin/env python

# Copyright 2017 Red Hat, Inc.
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

import os

import yaml

from tests.base import ZuulTestCase


class TestInventory(ZuulTestCase):

    tenant_config_file = 'config/inventory/main.yaml'

    def setUp(self):
        super(TestInventory, self).setUp()
        self.executor_server.hold_jobs_in_build = True
        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        self.fake_gerrit.addEvent(A.getPatchsetCreatedEvent(1))
        self.waitUntilSettled()

    def _get_build_inventory(self, name):
        build = self.getBuildByName(name)
        inv_path = os.path.join(build.jobdir.root, 'ansible', 'inventory.yaml')
        return yaml.safe_load(open(inv_path, 'r'))

    def test_single_inventory(self):

        inventory = self._get_build_inventory('single-inventory')

        all_nodes = ('ubuntu-xenial',)
        self.assertIn('all', inventory)
        self.assertIn('hosts', inventory['all'])
        self.assertIn('vars', inventory['all'])
        for node_name in all_nodes:
            self.assertIn(node_name, inventory['all']['hosts'])
        self.assertIn('zuul', inventory['all']['vars'])
        z_vars = inventory['all']['vars']['zuul']
        self.assertIn('executor', z_vars)
        self.assertIn('src_root', z_vars['executor'])
        self.assertIn('job', z_vars)
        self.assertEqual(z_vars['job'], 'single-inventory')

        self.executor_server.release()
        self.waitUntilSettled()

    def test_single_inventory_list(self):

        inventory = self._get_build_inventory('single-inventory-list')

        all_nodes = ('compute', 'controller')
        self.assertIn('all', inventory)
        self.assertIn('hosts', inventory['all'])
        self.assertIn('vars', inventory['all'])
        for node_name in all_nodes:
            self.assertIn(node_name, inventory['all']['hosts'])
        self.assertIn('zuul', inventory['all']['vars'])
        z_vars = inventory['all']['vars']['zuul']
        self.assertIn('executor', z_vars)
        self.assertIn('src_root', z_vars['executor'])
        self.assertIn('job', z_vars)
        self.assertEqual(z_vars['job'], 'single-inventory-list')

        self.executor_server.release()
        self.waitUntilSettled()

    def test_group_inventory(self):

        inventory = self._get_build_inventory('group-inventory')

        all_nodes = ('controller', 'compute1', 'compute2')
        self.assertIn('all', inventory)
        self.assertIn('hosts', inventory['all'])
        self.assertIn('vars', inventory['all'])
        for group_name in ('ceph-osd', 'ceph-monitor'):
            self.assertIn(group_name, inventory)
        for node_name in all_nodes:
            self.assertIn(node_name, inventory['all']['hosts'])
            self.assertIn(node_name,
                          inventory['ceph-monitor']['hosts'])
        self.assertIn('zuul', inventory['all']['vars'])
        z_vars = inventory['all']['vars']['zuul']
        self.assertIn('executor', z_vars)
        self.assertIn('src_root', z_vars['executor'])
        self.assertIn('job', z_vars)
        self.assertEqual(z_vars['job'], 'group-inventory')

        self.executor_server.release()
        self.waitUntilSettled()
