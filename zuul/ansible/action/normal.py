# Copyright 2017 Red Hat, Inc.
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

from ansible.module_utils.six.moves.urllib.parse import urlparse
from ansible.errors import AnsibleError

from zuul.ansible import paths
normal = paths._import_ansible_action_plugin('normal')

ALLOWED_URL_SCHEMES = ('https', 'http', 'ftp')


class ActionModule(normal.ActionModule):
    '''Override the normal action plugin

    :py:class:`ansible.plugins.normal.ActionModule` is run for every
    module that does not have a more specific matching action plugin.

    Our overridden version of it wraps the execution with checks to block
    undesired actions on localhost.
    '''

    def run(self, tmp=None, task_vars=None):
        '''Overridden primary method from the base class.'''

        if paths._is_localhost_task(self):
            if not self.dispatch_handler():
                raise AnsibleError("Executing local code is prohibited")
        return super(ActionModule, self).run(tmp, task_vars)

    def dispatch_handler(self):
        '''Run per-action handler if one exists.'''
        handler_name = 'handle_{action}'.format(action=self._task.action)
        handler = getattr(self, handler_name, None)
        if handler:
            paths._fail_if_local_module(self)
            handler()
            return True
        return False

    def handle_zuul_return(self):
        '''Allow zuul_return module on localhost.'''
        pass

    def handle_stat(self):
        '''Allow stat module on localhost if it doesn't touch unsafe files.

        The :ansible:module:`stat` can be useful in jobs for manipulating logs
        and artifacts.

        Block any access of files outside the zuul work dir.
        '''
        if self._task.args.get('get_mime') is not None:
            raise AnsibleError("get_mime on localhost is forbidden")
        paths._fail_if_unsafe(self._task.args['path'])

    def handle_file(self):
        '''Allow file module on localhost if it doesn't touch unsafe files.

        The :ansible:module:`file` can be useful in jobs for manipulating logs
        and artifacts.

        Block any access of files outside the zuul work dir.
        '''
        for arg in ('path', 'dest', 'name'):
            dest = self._task.args.get(arg)
            if dest:
                paths._fail_if_unsafe(dest)

    def handle_uri(self):
        '''Allow uri module on localhost if it doesn't touch unsafe files.

        The :ansible:module:`uri` can be used from the executor to do
        things like pinging readthedocs.org that otherwise don't need a node.
        However, it can also download content to a local file, or be used to
        read from file:/// urls.

        Block any use of url schemes other than https, http and ftp. Further,
        block any local file interaction that falls outside of the zuul
        work dir.
        '''
        # uri takes all the file arguments, so just let handle_file validate
        # them for us.
        self.handle_file()
        scheme = urlparse(self._task.args['url']).scheme
        if scheme not in ALLOWED_URL_SCHEMES:
            raise AnsibleError(
                "{scheme} urls are not allowed from localhost."
                " Only {allowed_schemes} are allowed".format(
                    scheme=scheme,
                    allowed_schemes=ALLOWED_URL_SCHEMES))
