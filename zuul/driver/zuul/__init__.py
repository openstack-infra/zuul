# Copyright 2016 Red Hat, Inc.
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

from zuul.driver import Driver, TriggerInterface
from zuul.driver.zuul.zuulmodel import ZuulTriggerEvent

from zuul.driver.zuul import zuultrigger

PARENT_CHANGE_ENQUEUED = 'parent-change-enqueued'
PROJECT_CHANGE_MERGED = 'project-change-merged'


class ZuulDriver(Driver, TriggerInterface):
    name = 'zuul'
    log = logging.getLogger("zuul.ZuulTrigger")

    def __init__(self):
        self.parent_change_enqueued_events = {}
        self.project_change_merged_events = {}

    def registerScheduler(self, scheduler):
        self.sched = scheduler

    def reconfigure(self, tenant):
        for pipeline in tenant.layout.pipelines.values():
            for ef in pipeline.manager.event_filters:
                if not isinstance(ef.trigger, zuultrigger.ZuulTrigger):
                    continue
                if PARENT_CHANGE_ENQUEUED in ef._types:
                    # parent-change-enqueued events need to be filtered by
                    # pipeline
                    for pipeline in ef._pipelines:
                        key = (tenant.name, pipeline)
                        self.parent_change_enqueued_events[key] = True
                elif PROJECT_CHANGE_MERGED in ef._types:
                    self.project_change_merged_events[tenant.name] = True

    def onChangeMerged(self, tenant, change, source):
        # Called each time zuul merges a change
        if self.project_change_merged_events.get(tenant.name):
            try:
                self._createProjectChangeMergedEvents(change, source)
            except Exception:
                self.log.exception(
                    "Unable to create project-change-merged events for "
                    "%s" % (change,))

    def onChangeEnqueued(self, tenant, change, pipeline):
        # Called each time a change is enqueued in a pipeline
        tenant_events = self.parent_change_enqueued_events.get(
            (tenant.name, pipeline.name))
        self.log.debug("onChangeEnqueued %s", tenant_events)
        if tenant_events:
            try:
                self._createParentChangeEnqueuedEvents(
                    change, pipeline, tenant)
            except Exception:
                self.log.exception(
                    "Unable to create parent-change-enqueued events for "
                    "%s in %s" % (change, pipeline))

    def _createProjectChangeMergedEvents(self, change, source):
        changes = source.getProjectOpenChanges(
            change.project)
        for open_change in changes:
            self._createProjectChangeMergedEvent(open_change)

    def _createProjectChangeMergedEvent(self, change):
        event = ZuulTriggerEvent()
        event.type = PROJECT_CHANGE_MERGED
        event.trigger_name = self.name
        event.project_hostname = change.project.canonical_hostname
        event.project_name = change.project.name
        event.change_number = change.number
        event.branch = change.branch
        event.change_url = change.url
        event.patch_number = change.patchset
        event.ref = change.ref
        self.sched.addEvent(event)

    def _createParentChangeEnqueuedEvents(self, change, pipeline, tenant):
        self.log.debug("Checking for changes needing %s:" % change)
        if not hasattr(change, 'needed_by_changes'):
            self.log.debug("  %s does not support dependencies" % type(change))
            return

        # This is very inefficient, especially on systems with large
        # numbers of github installations.  This can be improved later
        # with persistent storage of dependency information.
        needed_by_changes = set(change.needed_by_changes)
        for source in self.sched.connections.getSources():
            self.log.debug("  Checking source: %s", source)
            needed_by_changes.update(
                source.getChangesDependingOn(change, None, tenant))
        self.log.debug("  Following changes: %s", needed_by_changes)

        for needs in needed_by_changes:
            self._createParentChangeEnqueuedEvent(needs, pipeline)

    def _createParentChangeEnqueuedEvent(self, change, pipeline):
        event = ZuulTriggerEvent()
        event.type = PARENT_CHANGE_ENQUEUED
        event.trigger_name = self.name
        event.pipeline_name = pipeline.name
        event.project_hostname = change.project.canonical_hostname
        event.project_name = change.project.name
        event.change_number = change.number
        event.branch = change.branch
        event.change_url = change.url
        event.patch_number = change.patchset
        event.ref = change.ref
        self.sched.addEvent(event)

    def getTrigger(self, connection_name, config=None):
        return zuultrigger.ZuulTrigger(self, config)

    def getTriggerSchema(self):
        return zuultrigger.getSchema()
