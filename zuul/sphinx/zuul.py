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
from sphinx.domains import Domain, ObjType
from sphinx.directives import ObjectDescription


class ZuulConfigObject(ObjectDescription):
    pass


class ZuulConfigobjectDirective(ZuulConfigObject):
    has_content = False

    def before_content(self):
        self.env.ref_context['zuul:configobject'] = self.names[-1].lower()

    def handle_signature(self, sig, signode):
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
        obj = self.env.ref_context.get('zuul:configobject')
        attr_path = self.env.ref_context.get('zuul:attr_path', [])
        path = []
        if obj:
            path.append(obj)
        if attr_path:
            path.extend(attr_path)
        for x in path:
            signode += addnodes.desc_addname(x + '.', x + '.')
        signode += addnodes.desc_name(sig, sig)
        if 'required' in self.options:
            signode += addnodes.desc_annotation(' (required)', ' (required)')
        return sig

    def add_target_and_index(self, name, sig, signode):
        targetname = self.objtype + '-' + name
        if targetname not in self.state.document.ids:
            signode['names'].append(targetname)
            signode['ids'].append(targetname)
            signode['first'] = (not self.names)
            self.state.document.note_explicit_target(signode)

        indextext = '%s (%s)' % (name, self.objtype)
        self.indexnode['entries'].append(('single', indextext,
                                          targetname, '', None))


class ZuulValueDirective(ZuulConfigObject):
    has_content = True

    def handle_signature(self, sig, signode):
        signode += addnodes.desc_name(sig, sig)
        return sig

    def add_target_and_index(self, name, sig, signode):
        targetname = self.objtype + '-' + name
        if targetname not in self.state.document.ids:
            signode['names'].append(targetname)
            signode['ids'].append(targetname)
            signode['first'] = (not self.names)
            self.state.document.note_explicit_target(signode)

        indextext = '%s (%s)' % (name, self.objtype)
        self.indexnode['entries'].append(('single', indextext,
                                          targetname, '', None))


class ZuulDomain(Domain):
    name = 'zuul'
    label = 'Zuul'

    object_types = {
        'configobject': ObjType('configobject'),
        'attr': ObjType('attr'),
        'value': ObjType('value'),
    }

    directives = {
        'configobject': ZuulConfigobjectDirective,
        'attr': ZuulAttrDirective,
        'value': ZuulValueDirective,
    }


def setup(app):
    app.add_domain(ZuulDomain)
