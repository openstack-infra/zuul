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

from sphinx import addnodes
from sphinx.domains import Domain
from sphinx.directives import ObjectDescription


class ZuulConfigObject(ObjectDescription):
    object_names = {
        'attr': 'attribute',
        'configobject': 'configuration object',
    }

    def get_path(self):
        obj = self.env.ref_context.get('zuul:configobject')
        attr_path = self.env.ref_context.get('zuul:attr_path', [])
        path = []
        if obj:
            path.append(obj)
        if attr_path:
            path.extend(attr_path)
        return path

    @property
    def parent_pathname(self):
        return '.'.join(self.get_path())

    @property
    def full_pathname(self):
        name = self.names[-1].lower()
        return '.'.join(self.get_path() + [name])

    def add_target_and_index(self, name, sig, signode):
        targetname = self.objtype + '-' + self.full_pathname
        if targetname not in self.state.document.ids:
            signode['names'].append(targetname)
            signode['ids'].append(targetname)
            signode['first'] = (not self.names)
            self.state.document.note_explicit_target(signode)

        objname = self.object_names.get(self.objtype, self.objtype)
        if self.parent_pathname:
            indextext = '%s (%s of %s)' % (name, objname,
                                           self.parent_pathname)
        else:
            indextext = '%s (%s)' % (name, objname)
        self.indexnode['entries'].append(('single', indextext,
                                          targetname, '', None))


class ZuulConfigobjectDirective(ZuulConfigObject):
    has_content = True

    def before_content(self):
        self.env.ref_context['zuul:configobject'] = self.names[-1]

    def handle_signature(self, sig, signode):
        signode += addnodes.desc_name(sig, sig)
        return sig


class ZuulAttrDirective(ZuulConfigObject):
    has_content = True

    option_spec = {
        'required': lambda x: x,
    }

    def before_content(self):
        path = self.env.ref_context.setdefault('zuul:attr_path', [])
        path.append(self.names[-1])

    def after_content(self):
        path = self.env.ref_context.get('zuul:attr_path')
        if path:
            path.pop()

    def handle_signature(self, sig, signode):
        path = self.get_path()
        for x in path:
            signode += addnodes.desc_addname(x + '.', x + '.')
        signode += addnodes.desc_name(sig, sig)
        if 'required' in self.options:
            signode += addnodes.desc_annotation(' (required)', ' (required)')
        return sig


class ZuulValueDirective(ZuulConfigObject):
    has_content = True

    def handle_signature(self, sig, signode):
        signode += addnodes.desc_name(sig, sig)
        return sig


class ZuulDomain(Domain):
    name = 'zuul'
    label = 'Zuul'

    directives = {
        'configobject': ZuulConfigobjectDirective,
        'attr': ZuulAttrDirective,
        'value': ZuulValueDirective,
    }


def setup(app):
    app.add_domain(ZuulDomain)
