# Copyright 2014 OpenStack Foundation
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

import collections
import threading


class MergedQueue(object):
    def __init__(self):
        self.queue = collections.deque()
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.join_condition = threading.Condition(self.lock)
        self.tasks = 0

    def qsize(self):
        return len(self.queue)

    def empty(self):
        return self.qsize() == 0

    def put(self, item):
        # Returns the original item if added, or an updated equivalent
        # item if already enqueued.
        self.condition.acquire()
        ret = None
        try:
            for x in self.queue:
                if item == x:
                    ret = x
                    if hasattr(ret, 'merge'):
                        ret.merge(item)
            if ret is None:
                ret = item
                self.queue.append(item)
                self.condition.notify()
        finally:
            self.condition.release()
        return ret

    def get(self):
        self.condition.acquire()
        try:
            while True:
                try:
                    ret = self.queue.popleft()
                    self.join_condition.acquire()
                    self.tasks += 1
                    self.join_condition.release()
                    return ret
                except IndexError:
                    self.condition.wait()
        finally:
            self.condition.release()

    def task_done(self):
        self.join_condition.acquire()
        self.tasks -= 1
        self.join_condition.notify()
        self.join_condition.release()

    def join(self):
        self.join_condition.acquire()
        while self.tasks:
            self.join_condition.wait()
        self.join_condition.release()
