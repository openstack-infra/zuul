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

import fixtures
import os
import tempfile
import time

from tests.base import BaseTestCase

from zuul.executor.server import DiskAccountant


class FakeExecutor(object):
    def __init__(self):
        self.stopped_jobs = set()
        self.used = {}

    def stopJobByJobDir(self, jobdir):
        self.stopped_jobs.add(jobdir)

    def usage(self, dirname, used):
        self.used[dirname] = used


class TestDiskAccountant(BaseTestCase):
    def setUp(self):
        super(TestDiskAccountant, self).setUp()
        self.useFixture(fixtures.NestedTempfile())

    def test_disk_accountant(self):
        jobs_dir = tempfile.mkdtemp(
            dir=os.environ.get("ZUUL_TEST_ROOT", None))
        cache_dir = tempfile.mkdtemp()
        executor_server = FakeExecutor()
        da = DiskAccountant(jobs_dir, 1, executor_server.stopJobByJobDir,
                            cache_dir)
        da.start()

        try:
            jobdir = os.path.join(jobs_dir, '012345')
            os.mkdir(jobdir)
            testfile = os.path.join(jobdir, 'tfile')
            with open(testfile, 'w') as tf:
                tf.write(2 * 1024 * 1024 * '.')
                tf.flush()
                os.fsync(tf.fileno())

            # da should catch over-limit dir within 5 seconds
            for i in range(0, 50):
                if jobdir in executor_server.stopped_jobs:
                    break
                time.sleep(0.1)
            self.assertEqual(set([jobdir]), executor_server.stopped_jobs)
        finally:
            da.stop()
        self.assertFalse(da.thread.is_alive())

    def test_disk_accountant_no_limit(self):
        jobs_dir = tempfile.mkdtemp(
            dir=os.environ.get("ZUUL_TEST_ROOT", None))
        cache_dir = tempfile.mkdtemp()
        executor_server = FakeExecutor()
        da = DiskAccountant(jobs_dir, -1, executor_server.stopJobByJobDir,
                            cache_dir)
        da.start()
        self.assertFalse(da.running)
        da.stop()
        self.assertFalse(da.running)

    def test_cache_hard_links(self):
        root_dir = tempfile.mkdtemp(
            dir=os.environ.get("ZUUL_TEST_ROOT", None))
        jobs_dir = os.path.join(root_dir, 'jobs')
        os.mkdir(jobs_dir)
        cache_dir = os.path.join(root_dir, 'cache')
        os.mkdir(cache_dir)

        executor_server = FakeExecutor()
        da = DiskAccountant(jobs_dir, 1, executor_server.stopJobByJobDir,
                            cache_dir, executor_server.usage)
        da.start()
        self.addCleanup(da.stop)

        jobdir = os.path.join(jobs_dir, '012345')
        os.mkdir(jobdir)

        repo_dir = os.path.join(cache_dir, 'a.repo')
        os.mkdir(repo_dir)
        source_file = os.path.join(repo_dir, 'big_file')
        with open(source_file, 'w') as tf:
            tf.write(2 * 1024 * 1024 * '.')
        dest_link = os.path.join(jobdir, 'big_file')
        os.link(source_file, dest_link)

        # da should _not_ count this file. Wait for 5s to get noticed
        for i in range(0, 50):
            if jobdir in executor_server.used:
                break
            time.sleep(0.1)
        self.assertEqual(set(), executor_server.stopped_jobs)
        self.assertIn(jobdir, executor_server.used)
        self.assertTrue(executor_server.used[jobdir] <= 1)
