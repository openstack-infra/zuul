# Copyright 2016 IBM Corp.
#
# This file is part of Zuul
#
# This file is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This file is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see <http://www.gnu.org/licenses/>.

import time

from ansible.executor.task_result import TaskResult
from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    def __init__(self, *args, **kw):
        super(CallbackModule, self).__init__(*args, **kw)
        self._elapsed_time = 0.0
        self._task_start_time = None
        self._play = None

    def v2_playbook_on_play_start(self, play):
        self._play = play

    def playbook_on_task_start(self, name, is_conditional):
        self._task_start_time = time.time()

    def v2_on_any(self, *args, **kw):
        result = None
        if args and isinstance(args[0], TaskResult):
            result = args[0]
        if not result:
            return

        if self._task_start_time is not None:
            task_time = time.time() - self._task_start_time
            self._elapsed_time += task_time
        if self._play and result._host:
            manager = self._play.get_variable_manager()
            facts = dict(elapsed_time=int(self._elapsed_time))

            manager.set_nonpersistent_facts(result._host, facts)
        self._task_start_time = None
