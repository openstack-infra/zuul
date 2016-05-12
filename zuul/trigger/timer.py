# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2013 OpenStack Foundation
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

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import voluptuous as v
from zuul.model import EventFilter, TriggerEvent
from zuul.trigger import BaseTrigger


class TimerTrigger(BaseTrigger):
    name = 'timer'
    log = logging.getLogger("zuul.Timer")

    def __init__(self, trigger_config={}, sched=None, connection=None):
        super(TimerTrigger, self).__init__(trigger_config, sched, connection)
        self.apsched = BackgroundScheduler()
        self.apsched.start()

    def _onTrigger(self, pipeline_name, timespec):
        for project in self.sched.layout.projects.values():
            event = TriggerEvent()
            event.type = 'timer'
            event.timespec = timespec
            event.forced_pipeline = pipeline_name
            event.project_name = project.name
            self.log.debug("Adding event %s" % event)
            self.sched.addEvent(event)

    def stop(self):
        self.apsched.shutdown()

    def getEventFilters(self, trigger_conf):
        def toList(item):
            if not item:
                return []
            if isinstance(item, list):
                return item
            return [item]

        efilters = []
        for trigger in toList(trigger_conf):
            f = EventFilter(trigger=self,
                            types=['timer'],
                            timespecs=toList(trigger['time']))

            efilters.append(f)

        return efilters

    def postConfig(self):
        for job in self.apsched.get_jobs():
            job.remove()
        for pipeline in self.sched.layout.pipelines.values():
            for ef in pipeline.manager.event_filters:
                if ef.trigger != self:
                    continue
                for timespec in ef.timespecs:
                    parts = timespec.split()
                    if len(parts) < 5 or len(parts) > 6:
                        self.log.error(
                            "Unable to parse time value '%s' "
                            "defined in pipeline %s" % (
                                timespec,
                                pipeline.name))
                        continue
                    minute, hour, dom, month, dow = parts[:5]
                    if len(parts) > 5:
                        second = parts[5]
                    else:
                        second = None
                    trigger = CronTrigger(day=dom, day_of_week=dow, hour=hour,
                                          minute=minute, second=second)

                    self.apsched.add_job(self._onTrigger, trigger=trigger,
                                         args=(pipeline.name, timespec,))


def getSchema():
    timer_trigger = {v.Required('time'): str}
    return timer_trigger
