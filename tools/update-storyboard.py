#!/usr/bin/env python
# Copyright (C) 2016 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script updates the Zuul v3 Storyboard.  It uses a .boartty.yaml
# file to get credential information.

import requests
import boartty.config
import boartty.sync
import logging  # noqa
from pprint import pprint as p  # noqa


class App(object):
    pass


def get_tasks(sync):
    task_list = []
    for story in sync.get('/v1/stories?tags=zuulv3'):
        print("Story %s: %s" % (story['id'], story['title']))
        for task in sync.get('/v1/stories/%s/tasks' % (story['id'])):
            print("  %s" % (task['title'],))
            task_list.append(task)
    return task_list


def task_in_lane(task, lane):
    for item in lane['worklist']['items']:
        if 'task' in item and item['task']['id'] == task['id']:
            return True
    return False


def add_task(sync, task, lane):
    print("Add task %s to %s" % (task['id'], lane['worklist']['id']))
    r = sync.post('v1/worklists/%s/items/' % lane['worklist']['id'],
                  dict(item_id=task['id'],
                       item_type='task',
                       list_position=0))
    print(r)


def remove_task(sync, task, lane):
    print("Remove task %s from %s" % (task['id'], lane['worklist']['id']))
    for item in lane['worklist']['items']:
        if 'task' in item and item['task']['id'] == task['id']:
            r = sync.delete('v1/worklists/%s/items/' % lane['worklist']['id'],
                            dict(item_id=item['id']))
            print(r)


MAP = {
    'todo': ['New', 'Backlog', 'Todo'],
    'inprogress': ['In Progress', 'Blocked'],
    'review': ['In Progress', 'Blocked'],
    'merged': None,
    'invalid': None,
}


def main():
    requests.packages.urllib3.disable_warnings()
    # logging.basicConfig(level=logging.DEBUG)
    app = App()
    app.config = boartty.config.Config('openstack')
    sync = boartty.sync.Sync(app, False)
    board = sync.get('v1/boards/41')
    tasks = get_tasks(sync)

    lanes = dict()
    for lane in board['lanes']:
        lanes[lane['worklist']['title']] = lane

    for task in tasks:
        ok_lanes = MAP[task['status']]
        task_found = False
        for lane_name, lane in lanes.items():
            if task_in_lane(task, lane):
                if ok_lanes and lane_name in ok_lanes:
                    task_found = True
                else:
                    remove_task(sync, task, lane)
        if ok_lanes and not task_found:
            add_task(sync, task, lanes[ok_lanes[0]])


if __name__ == '__main__':
    main()
