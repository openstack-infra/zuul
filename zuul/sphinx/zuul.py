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
from sphinx.roles import XRefRole
from sphinx.directives import ObjectDescription
from sphinx.util.nodes import make_refnode
from docutils import nodes

from typing import Dict # noqa


class ZuulConfigObject(ObjectDescription):
    object_names = {
        'attr': 'attribute',
    }

    def get_path(self):
        attr_path = self.env.ref_context.get('zuul:attr_path', [])
        path = []
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
            objects = self.env.domaindata['zuul']['objects']
            if targetname in objects:
                self.state_machine.reporter.warning(
                    'duplicate object description of %s, ' % targetname +
                    'other instance in ' +
                    self.env.doc2path(objects[targetname][0]) +
                    ', use :noindex: for one of them',
                    line=self.lineno)
            objects[targetname] = (self.env.docname, self.objtype)

        objname = self.object_names.get(self.objtype, self.objtype)
        if self.parent_pathname:
            indextext = '%s (%s of %s)' % (name, objname,
                                           self.parent_pathname)
        else:
            indextext = '%s (%s)' % (name, objname)
        self.indexnode['entries'].append(('single', indextext,
                                          targetname, '', None))


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
        'attr': ZuulAttrDirective,
        'value': ZuulValueDirective,
    }

    roles = {
        'attr': XRefRole(innernodeclass=nodes.inline,  # type: ignore
                         warn_dangling=True),
    }

    initial_data = {
        'objects': {},
    }  # type: Dict[str, Dict]

    def resolve_xref(self, env, fromdocname, builder, type, target,
                     node, contnode):
        objects = self.data['objects']
        name = type + '-' + target
        obj = objects.get(name)
        if obj:
            return make_refnode(builder, fromdocname, obj[0], name,
                                contnode, name)

    def clear_doc(self, docname):
        for fullname, (fn, _l) in list(self.data['objects'].items()):
            if fn == docname:
                del self.data['objects'][fullname]


def setup(app):
    app.add_domain(ZuulDomain)
