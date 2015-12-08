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

import logging

from tests.base import (
    ZuulTestCase,
)

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-32s '
                    '%(levelname)-8s %(message)s')


class TestV3(ZuulTestCase):
    # A temporary class to hold new tests while others are disabled

    def test_jobs_launched(self):
        "Test that jobs are launched and a change is merged"

        A = self.fake_gerrit.addFakeChange('org/project', 'master', 'A')
        A.addApproval('CRVW', 2)
        self.fake_gerrit.addEvent(A.addApproval('APRV', 1))
        self.waitUntilSettled()
        self.assertEqual(self.getJobFromHistory('project-merge').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test1').result,
                         'SUCCESS')
        self.assertEqual(self.getJobFromHistory('project-test2').result,
                         'SUCCESS')
        self.assertEqual(A.data['status'], 'MERGED')
        self.assertEqual(A.reported, 2)

        self.assertReportedStat('gerrit.event.comment-added', value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.current_changes',
                                value='1|g')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.job.project-merge.SUCCESS',
                                value='1|c')
        self.assertReportedStat('zuul.pipeline.gate.resident_time', kind='ms')
        self.assertReportedStat('zuul.pipeline.gate.total_changes',
                                value='1|c')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.resident_time', kind='ms')
        self.assertReportedStat(
            'zuul.pipeline.gate.org.project.total_changes', value='1|c')

        for build in self.builds:
            self.assertEqual(build.parameters['ZUUL_VOTING'], '1')
