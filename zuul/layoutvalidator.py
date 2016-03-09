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

    approval = v.Schema({'username': str,
                         'email-filter': str,
                         'email': str,
                         'older-than': str,
                         'newer-than': str,
                         }, extra=True)

    require = {'approval': toList(approval),
               'open': bool,
               'current-patchset': bool,
               'status': toList(str)}

    reject = {'approval': toList(approval)}

    window = v.All(int, v.Range(min=0))
    window_floor = v.All(int, v.Range(min=1))
    window_type = v.Any('linear', 'exponential')
    window_factor = v.All(int, v.Range(min=1))

    pipeline = {v.Required('name'): str,
                v.Required('manager'): manager,
                'source': str,
                'precedence': precedence,
                'description': str,
                'require': require,
                'reject': reject,
                'success-message': str,
                'failure-message': str,
                'merge-failure-message': str,
                'footer-message': str,
                'dequeue-on-new-patchset': bool,
                'ignore-dependencies': bool,
                'disable-after-consecutive-failures':
                    v.All(int, v.Range(min=1)),
                'window': window,
                'window-floor': window_floor,
                'window-increase-type': window_type,
                'window-increase-factor': window_factor,
                'window-decrease-type': window_type,
                'window-decrease-factor': window_factor,
                }

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

    skip_if = {'project': str,
               'branch': str,
               'all-files-match-any': toList(str),
               }

    job = {v.Required('name'): str,
           'queue-name': str,
           'failure-message': str,
           'success-message': str,
           'failure-pattern': str,
           'success-pattern': str,
           'hold-following-changes': bool,
           'voting': bool,
           'mutex': str,
           'tags': toList(str),
           'parameter-function': str,
           'branch': toList(str),
           'files': toList(str),
           'swift': toList(swift),
           'skip-if': toList(skip_if),
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

    def getDriverSchema(self, dtype, connections):
        # TODO(jhesketh): Make the driver discovery dynamic
        connection_drivers = {
            'trigger': {
                'gerrit': 'zuul.trigger.gerrit',
            },
            'reporter': {
                'gerrit': 'zuul.reporter.gerrit',
                'smtp': 'zuul.reporter.smtp',
            },
        }
        standard_drivers = {
            'trigger': {
                'timer': 'zuul.trigger.timer',
                'zuul': 'zuul.trigger.zuultrigger',
            }
        }

        schema = {}
        # Add the configured connections as available layout options
        for connection_name, connection in connections.items():
            for dname, dmod in connection_drivers.get(dtype, {}).items():
                if connection.driver_name == dname:
                    schema[connection_name] = toList(__import__(
                        connection_drivers[dtype][dname],
                        fromlist=['']).getSchema())

        # Standard drivers are always available and don't require a unique
        # (connection) name
        for dname, dmod in standard_drivers.get(dtype, {}).items():
            schema[dname] = toList(__import__(
                standard_drivers[dtype][dname], fromlist=['']).getSchema())

        return schema

    def getSchema(self, data, connections=None):
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

        # TODO(jhesketh): source schema is still defined above as sources
        # currently aren't key/value so there is nothing to validate. Need to
        # revisit this and figure out how to allow drivers with and without
        # params. eg support all:
        #   source: gerrit
        # and
        #   source:
        #     gerrit:
        #       - val
        #       - val2
        # and
        #   source:
        #     gerrit: something
        # etc...
        self.pipeline['trigger'] = v.Required(
            self.getDriverSchema('trigger', connections))
        for action in ['start', 'success', 'failure', 'merge-failure',
                       'disabled']:
            self.pipeline[action] = self.getDriverSchema('reporter',
                                                         connections)

        # Gather our sub schemas
        schema = v.Schema({'includes': self.includes,
                           v.Required('pipelines'): [self.pipeline],
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

    def extraDriverValidation(self, dtype, driver_data, connections=None):
        # Some drivers may have extra validation to run on the layout
        # TODO(jhesketh): Make the driver discovery dynamic
        connection_drivers = {
            'trigger': {
                'gerrit': 'zuul.trigger.gerrit',
            },
            'reporter': {
                'gerrit': 'zuul.reporter.gerrit',
                'smtp': 'zuul.reporter.smtp',
            },
        }
        standard_drivers = {
            'trigger': {
                'timer': 'zuul.trigger.timer',
                'zuul': 'zuul.trigger.zuultrigger',
            }
        }

        for dname, d_conf in driver_data.items():
            for connection_name, connection in connections.items():
                if connection_name == dname:
                    if (connection.driver_name in
                        connection_drivers.get(dtype, {}).keys()):
                        module = __import__(
                            connection_drivers[dtype][connection.driver_name],
                            fromlist=['']
                        )
                        if 'validate_conf' in dir(module):
                            module.validate_conf(d_conf)
                    break
            if dname in standard_drivers.get(dtype, {}).keys():
                module = __import__(standard_drivers[dtype][dname],
                                    fromlist=[''])
                if 'validate_conf' in dir(module):
                    module.validate_conf(d_conf)

    def validate(self, data, connections=None):
        schema = LayoutSchema().getSchema(data, connections)
        schema(data)
        self.checkDuplicateNames(data['pipelines'], ['pipelines'])
        if 'jobs' in data:
            self.checkDuplicateNames(data['jobs'], ['jobs'])
        self.checkDuplicateNames(data['projects'], ['projects'])
        if 'project-templates' in data:
            self.checkDuplicateNames(
                data['project-templates'], ['project-templates'])

        for pipeline in data['pipelines']:
            self.extraDriverValidation('trigger', pipeline['trigger'],
                                       connections)
            for action in ['start', 'success', 'failure', 'merge-failure']:
                if action in pipeline:
                    self.extraDriverValidation('reporter', pipeline[action],
                                               connections)
