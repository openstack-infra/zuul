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
        'var': 'variable',
    }

    def get_path(self):
        return self.env.ref_context.get('zuuldoc:attr_path', [])

    def get_display_path(self):
        return self.env.ref_context.get('zuuldoc:display_attr_path', [])

    @property
    def parent_pathname(self):
        return '.'.join(self.get_display_path())

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
            objects = self.env.domaindata['zuuldoc']['objects']
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
        'default': lambda x: x,
        'noindex': lambda x: x,
    }

    def before_content(self):
        path = self.env.ref_context.setdefault('zuuldoc:attr_path', [])
        path.append(self.names[-1])
        path = self.env.ref_context.setdefault('zuuldoc:display_attr_path', [])
        path.append(self.names[-1])

    def after_content(self):
        path = self.env.ref_context.get('zuuldoc:attr_path')
        if path:
            path.pop()
        path = self.env.ref_context.get('zuuldoc:display_attr_path')
        if path:
            path.pop()

    def handle_signature(self, sig, signode):
        path = self.get_display_path()
        signode['is_multiline'] = True
        line = addnodes.desc_signature_line()
        line['add_permalink'] = True
        for x in path:
            line += addnodes.desc_addname(x + '.', x + '.')
        line += addnodes.desc_name(sig, sig)
        if 'required' in self.options:
            line += addnodes.desc_annotation(' (required)', ' (required)')
        signode += line
        if 'default' in self.options:
            line = addnodes.desc_signature_line()
            line += addnodes.desc_type('Default: ', 'Default: ')
            line += nodes.literal(self.options['default'],
                                  self.options['default'])
            signode += line
        return sig


class ZuulValueDirective(ZuulConfigObject):
    has_content = True

    def handle_signature(self, sig, signode):
        signode += addnodes.desc_name(sig, sig)
        return sig


class ZuulVarDirective(ZuulConfigObject):
    has_content = True

    option_spec = {
        'type': lambda x: x,
        'hidden': lambda x: x,
        'noindex': lambda x: x,
    }

    type_map = {
        'list': '[]',
        'dict': '{}',
    }

    def get_type_str(self):
        if 'type' in self.options:
            return self.type_map[self.options['type']]
        return ''

    def before_content(self):
        path = self.env.ref_context.setdefault('zuuldoc:attr_path', [])
        element = self.names[-1]
        path.append(element)
        path = self.env.ref_context.setdefault('zuuldoc:display_attr_path', [])
        element = self.names[-1] + self.get_type_str()
        path.append(element)

    def after_content(self):
        path = self.env.ref_context.get('zuuldoc:attr_path')
        if path:
            path.pop()
        path = self.env.ref_context.get('zuuldoc:display_attr_path')
        if path:
            path.pop()

    def handle_signature(self, sig, signode):
        if 'hidden' in self.options:
            return sig
        path = self.get_display_path()
        for x in path:
            signode += addnodes.desc_addname(x + '.', x + '.')
        signode += addnodes.desc_name(sig, sig)
        return sig


class ZuulStatDirective(ZuulConfigObject):
    has_content = True

    option_spec = {
        'type': lambda x: x,
        'hidden': lambda x: x,
        'noindex': lambda x: x,
    }

    def before_content(self):
        path = self.env.ref_context.setdefault('zuuldoc:attr_path', [])
        element = self.names[-1]
        path.append(element)
        path = self.env.ref_context.setdefault('zuuldoc:display_attr_path', [])
        element = self.names[-1]
        path.append(element)

    def after_content(self):
        path = self.env.ref_context.get('zuuldoc:attr_path')
        if path:
            path.pop()
        path = self.env.ref_context.get('zuuldoc:display_attr_path')
        if path:
            path.pop()

    def handle_signature(self, sig, signode):
        if 'hidden' in self.options:
            return sig
        path = self.get_display_path()
        for x in path:
            signode += addnodes.desc_addname(x + '.', x + '.')
        signode += addnodes.desc_name(sig, sig)
        if 'type' in self.options:
            t = ' (%s)' % self.options['type']
            signode += addnodes.desc_annotation(t, t)
        return sig


class ZuulAbbreviatedXRefRole(XRefRole):

    def process_link(self, env, refnode, has_explicit_title, title,
                     target):
        title, target = super(ZuulAbbreviatedXRefRole, self).process_link(
            env, refnode, has_explicit_title, title, target)
        if not has_explicit_title:
            title = title.split('.')[-1]
        return title, target


class ZuulDomain(Domain):
    name = 'zuuldoc'
    label = 'Zuul'

    directives = {
        'attr': ZuulAttrDirective,
        'value': ZuulValueDirective,
        'var': ZuulVarDirective,
        'stat': ZuulStatDirective,
    }

    roles = {
        'attr': XRefRole(innernodeclass=nodes.inline,  # type: ignore
                         warn_dangling=True),
        'value': ZuulAbbreviatedXRefRole(
            innernodeclass=nodes.inline,  # type: ignore
            warn_dangling=True),
        'var': XRefRole(innernodeclass=nodes.inline,  # type: ignore
                        warn_dangling=True),
        'stat': XRefRole(innernodeclass=nodes.inline,  # type: ignore
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
