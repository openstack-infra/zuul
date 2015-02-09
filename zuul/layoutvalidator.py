# Copyright 2013 OpenStack Foundation
# Copyright 2013 Antoine "hashar" Musso
# Copyright 2013 Wikimedia Foundation Inc.
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import voluptuous as v
import string

from zuul.trigger import gerrit


# Several forms accept either a single item or a list, this makes
# specifying that in the schema easy (and explicit).
def toList(x):
    return v.Any([x], x)


class LayoutSchema(object):
    include = {'python-file': str}
    includes = [include]

    manager = v.Any('IndependentPipelineManager',
                    'DependentPipelineManager')

    precedence = v.Any('normal', 'low', 'high')

    variable_dict = v.Schema({}, extra=True)

    require_approval = v.Schema({'username': str,
                                 'email-filter': str,
                                 'email': str,
                                 'older-than': str,
                                 'newer-than': str,
                                 }, extra=True)

    gerrit_trigger = {v.Required('event'):
                      toList(v.Any('patchset-created',
                                   'draft-published',
                                   'change-abandoned',
                                   'change-restored',
                                   'change-merged',
                                   'comment-added',
                                   'ref-updated')),
                      'comment_filter': toList(str),
                      'comment': toList(str),
                      'email_filter': toList(str),
                      'email': toList(str),
                      'username_filter': toList(str),
                      'username': toList(str),
                      'branch': toList(str),
                      'ref': toList(str),
                      'approval': toList(variable_dict),
                      'require-approval': toList(require_approval),
                      }

    timer_trigger = {v.Required('time'): str}

    zuul_trigger = {v.Required('event'):
                    toList(v.Any('parent-change-enqueued',
                                 'project-change-merged')),
                    'pipeline': toList(str),
                    'require-approval': toList(require_approval),
                    }

    trigger = v.Required({'gerrit': toList(gerrit_trigger),
                          'timer': toList(timer_trigger),
                          'zuul': toList(zuul_trigger)})

    report_actions = {'gerrit': variable_dict,
                      'smtp': {'to': str,
                               'from': str,
                               'subject': str,
                               },
                      }

    require = {'approval': toList(require_approval),
               'open': bool,
               'current-patchset': bool,
               'status': toList(str)}

    window = v.All(int, v.Range(min=0))
    window_floor = v.All(int, v.Range(min=1))
    window_type = v.Any('linear', 'exponential')
    window_factor = v.All(int, v.Range(min=1))

    pipeline = {v.Required('name'): str,
                v.Required('manager'): manager,
                'source': v.Any('gerrit'),
                'precedence': precedence,
                'description': str,
                'require': require,
                'success-message': str,
                'failure-message': str,
                'merge-failure-message': str,
                'footer-message': str,
                'dequeue-on-new-patchset': bool,
                'ignore-dependencies': bool,
                'trigger': trigger,
                'success': report_actions,
                'failure': report_actions,
                'merge-failure': report_actions,
                'start': report_actions,
                'window': window,
                'window-floor': window_floor,
                'window-increase-type': window_type,
                'window-increase-factor': window_factor,
                'window-decrease-type': window_type,
                'window-decrease-factor': window_factor,
                }
    pipelines = [pipeline]

    project_template = {v.Required('name'): str}
    project_templates = [project_template]

    swift = {v.Required('name'): str,
             'container': str,
             'expiry': int,
             'max_file_size': int,
             'max-file-size': int,
             'max_file_count': int,
             'max-file-count': int,
             'logserver_prefix': str,
             'logserver-prefix': str,
             }

    job = {v.Required('name'): str,
           'queue-name': str,
           'failure-message': str,
           'success-message': str,
           'failure-pattern': str,
           'success-pattern': str,
           'hold-following-changes': bool,
           'voting': bool,
           'parameter-function': str,
           'branch': toList(str),
           'files': toList(str),
           'swift': toList(swift),
           }
    jobs = [job]

    job_name = v.Schema(v.Match("^\S+$"))

    def validateJob(self, value, path=[]):
        if isinstance(value, list):
            for (i, val) in enumerate(value):
                self.validateJob(val, path + [i])
        elif isinstance(value, dict):
            for k, val in value.items():
                self.validateJob(val, path + [k])
        else:
            self.job_name.schema(value)

    def validateTemplateCalls(self, calls):
        """ Verify a project pass the parameters required
            by a project-template
        """
        for call in calls:
            schema = self.templates_schemas[call.get('name')]
            schema(call)

    def collectFormatParam(self, tree):
        """In a nested tree of string, dict and list, find out any named
           parameters that might be used by str.format().  This is used to find
           out whether projects are passing all the required parameters when
           using a project template.

            Returns a set() of all the named parameters found.
        """
        parameters = set()
        if isinstance(tree, str):
            # parse() returns a tuple of
            # (literal_text, field_name, format_spec, conversion)
            # We are just looking for field_name
            parameters = set([t[1] for t in string.Formatter().parse(tree)
                              if t[1] is not None])
        elif isinstance(tree, list):
            for item in tree:
                parameters.update(self.collectFormatParam(item))
        elif isinstance(tree, dict):
            for item in tree:
                parameters.update(self.collectFormatParam(tree[item]))

        return parameters

    def getSchema(self, data):
        if not isinstance(data, dict):
            raise Exception("Malformed layout configuration: top-level type "
                            "should be a dictionary")
        pipelines = data.get('pipelines')
        if not pipelines:
            pipelines = []
        pipelines = [p['name'] for p in pipelines if 'name' in p]

        # Whenever a project uses a template, it better have to exist
        project_templates = data.get('project-templates', [])
        template_names = [t['name'] for t in project_templates
                          if 'name' in t]

        # A project using a template must pass all parameters to it.
        # We first collect each templates parameters and craft a new
        # schema for each of the template. That will later be used
        # by validateTemplateCalls().
        self.templates_schemas = {}
        for t_name in template_names:
            # Find out the parameters used inside each templates:
            template = [t for t in project_templates
                        if t['name'] == t_name]
            template_parameters = self.collectFormatParam(template)

            # Craft the templates schemas
            schema = {v.Required('name'): v.Any(*template_names)}
            for required_param in template_parameters:
                # special case 'name' which will be automatically provided
                if required_param == 'name':
                    continue
                # add this template parameters as requirements:
                schema.update({v.Required(required_param): str})

            # Register the schema for validateTemplateCalls()
            self.templates_schemas[t_name] = v.Schema(schema)

        project = {'name': str,
                   'merge-mode': v.Any('merge', 'merge-resolve,',
                                       'cherry-pick'),
                   'template': self.validateTemplateCalls,
                   }

        # And project should refers to existing pipelines
        for p in pipelines:
            project[p] = self.validateJob
        projects = [project]

        # Sub schema to validate a project template has existing
        # pipelines and jobs.
        project_template = {'name': str}
        for p in pipelines:
            project_template[p] = self.validateJob
        project_templates = [project_template]
        # Gather our sub schemas
        schema = v.Schema({'includes': self.includes,
                           v.Required('pipelines'): self.pipelines,
                           'jobs': self.jobs,
                           'project-templates': project_templates,
                           v.Required('projects'): projects,
                           })
        return schema


class LayoutValidator(object):
    def checkDuplicateNames(self, data, path):
        items = []
        for i, item in enumerate(data):
            if item['name'] in items:
                raise v.Invalid("Duplicate name: %s" % item['name'],
                                path + [i])
            items.append(item['name'])

    def validate(self, data):
        schema = LayoutSchema().getSchema(data)
        schema(data)
        self.checkDuplicateNames(data['pipelines'], ['pipelines'])
        if 'jobs' in data:
            self.checkDuplicateNames(data['jobs'], ['jobs'])
        self.checkDuplicateNames(data['projects'], ['projects'])
        if 'project-templates' in data:
            self.checkDuplicateNames(
                data['project-templates'], ['project-templates'])
        for pipeline in data['pipelines']:
            if 'gerrit' in pipeline['trigger']:
                gerrit.validate_trigger(pipeline['trigger'])
