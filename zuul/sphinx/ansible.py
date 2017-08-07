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

from docutils import nodes
from sphinx.domains import Domain

MODULE_URL = 'http://docs.ansible.com/ansible/latest/{module_name}_module.html'


def ansible_module_role(
        name, rawtext, text, lineno, inliner, options={}, content=[]):
    """Link to an upstream Ansible module.

    Returns 2 part tuple containing list of nodes to insert into the
    document and a list of system messages.  Both are allowed to be
    empty.

    :param name: The role name used in the document.
    :param rawtext: The entire markup snippet, with role.
    :param text: The text marked with the role.
    :param lineno: The line number where rawtext appears in the input.
    :param inliner: The inliner instance that called us.
    :param options: Directive options for customization.
    :param content: The directive content for customization.
    """
    node = nodes.reference(
        rawtext, "Ansible {module_name} module".format(module_name=text),
        refuri=MODULE_URL.format(module_name=text), **options)
    return ([node], [])


class AnsibleDomain(Domain):
    name = 'ansible'
    label = 'Ansible'

    roles = {
        'module': ansible_module_role,
    }


def setup(app):
    app.add_domain(AnsibleDomain)
