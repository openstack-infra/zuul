# Copyright 2016 Red Hat, Inc.
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

import imp
import os

from ansible import constants as C
from ansible.errors import AnsibleError
import ansible.modules
import ansible.plugins.action
import ansible.plugins.lookup


def _safe_find_needle(super, dirname, needle):
    result = super._find_needle(dirname, needle)
    # find_needle is only used for source files so it is safe to allow the
    # trusted folder where trusted roles reside
    if not _is_safe_path(result, allow_trusted=True):
        fail_dict = _fail_dict(_full_path(result))
        raise AnsibleError("{msg}. Invalid path: {path}".format(
            msg=fail_dict['msg'], path=fail_dict['path']))
    return result


def _full_path(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def _is_safe_path(path, allow_trusted=False):

    home_path = os.path.abspath(os.path.expanduser('~'))
    allowed_paths = [home_path]
    if allow_trusted:
        allowed_paths.append(
            os.path.abspath(os.path.join(home_path, '../trusted')))
        allowed_paths.append(
            os.path.abspath(os.path.join(home_path, '../untrusted')))

    def _is_safe(path_to_check):
        for allowed_path in allowed_paths:
            if path_to_check.startswith(allowed_path):
                return True
        return False

    # We need to really check the whole subtree starting from path. So first
    # start with the root and do an os.walk if path resolves to a directory.
    full_path = _full_path(path)
    if not _is_safe(full_path):
        return False

    # Walk the whole tree and check dirs and files. In order to mitigate
    # chained symlink attacks we also need to follow symlinks.
    visited = set()
    for root, dirs, files in os.walk(full_path, followlinks=True):

        # We recurse with follow links so check root first, then the files.
        # The dirs will be checked during recursion.
        full_root = _full_path(root)
        if not _is_safe(full_root):
            return False

        # NOTE: os.walk can lead to infinite recursion when following links
        # so filter out the dirs for further processing if we already checked
        # this one.
        if full_root in visited:
            del dirs[:]
            # we already checked the files here so we can just continue to the
            # next iteration
            continue
        visited.add(full_root)

        for entry in files:
            full_path = _full_path(os.path.join(root, entry))
            if not _is_safe(full_path):
                return False
    return True


def _fail_dict(path, prefix='Accessing files from'):
    return dict(
        failed=True,
        path=path,
        msg="{prefix} outside the working dir {curdir} is prohibited".format(
            prefix=prefix,
            curdir=os.path.abspath(os.path.curdir)))


def _fail_if_unsafe(path, allow_trusted=False):
    if not _is_safe_path(path, allow_trusted):
        msg_dict = _fail_dict(path)
        raise AnsibleError(msg_dict['msg'])


def _import_ansible_action_plugin(name):
    # Ansible forces the import of our action plugins
    # (zuul.ansible.action.foo) as ansible.plugins.action.foo, which
    # is the import path of the ansible implementation.  Our
    # implementations need to subclass that, but if we try to import
    # it with that name, we will get our own module.  This bypasses
    # Python's module namespace to load the actual ansible modules.
    # We need to give it a name, however.  If we load it with its
    # actual name, we will end up overwriting our module in Python's
    # namespace, causing infinite recursion.  So we supply an
    # otherwise unused name for the module:
    # zuul.ansible.protected.action.foo.

    return imp.load_module(
        'zuul.ansible.protected.action.' + name,
        *imp.find_module(name, ansible.plugins.action.__path__))


def _import_ansible_lookup_plugin(name):
    # See _import_ansible_action_plugin

    return imp.load_module(
        'zuul.ansible.protected.lookup.' + name,
        *imp.find_module(name, ansible.plugins.lookup.__path__))


def _is_official_module(module):
    task_module_path = module._shared_loader_obj.module_loader.find_plugin(
        module._task.action)
    ansible_module_paths = [os.path.dirname(ansible.modules.__file__)]
    # Also check library path in ansible.cfg for action plugins like
    # zuul_return.
    ansible_module_paths.extend(C.DEFAULT_MODULE_PATH)

    # If the module is not beneath the main ansible library path that means
    # someone has included a module with a playbook or a role that has the
    # same name as one of the builtin modules. Normally we don't care, but for
    # local execution it's a problem because their version could subvert our
    # path checks and/or do other things on the local machine that we don't
    # want them to do.
    for path in ansible_module_paths:
        if task_module_path.startswith(path):
            return True
    return False


def _fail_module_dict(module_name):
    return dict(
        failed=True,
        msg="Local execution of overridden module {name} is forbidden".format(
            name=module_name))


def _fail_if_local_module(module):
    if not _is_official_module(module):
        msg_dict = _fail_module_dict(module._task.action)
        raise AnsibleError(msg_dict['msg'])


def _is_localhost_task(task):

    # remote_addr is what's in the value of ansible_host and/or the opposite
    # side of a mapping. So if you had an inventory with:
    #
    # all:
    #   hosts:
    #     ubuntu-xenial:
    #       ansible_connection: ssh
    #       ansible_host: 23.253.109.74
    # remote_addr would be 23.253.109.74.
    #
    # localhost is special, since it's not in the inventory but instead is
    # added directly by ansible.
    #
    # The only way a user could supply a remote_addr with arbitrary ipv6
    # values is if they used add_host - which we don't let unprivileged code
    # do.

    if (task._play_context.connection == 'local'
        or task._play_context.remote_addr == 'localhost'
        or task._task.delegate_to == 'localhost'):
        return True
    return False


def _sanitize_filename(name):
    return ''.join(c for c in name if c.isalnum())
