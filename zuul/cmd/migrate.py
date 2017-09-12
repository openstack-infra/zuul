#!/usr/bin/env python

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

# TODO(mordred):
# * Read and apply filters from the jobs: section
# * Figure out shared job queues
# * Emit job definitions
#   * figure out from builders whether or not it's a normal job or a
#     a devstack-legacy job
#   * Handle emitting arbitrary tox jobs (see tox-py27dj18)

import argparse
import collections
import copy
import itertools
import logging
import os
import re
from typing import Any, Dict, List, Optional  # flake8: noqa

import jenkins_jobs.builder
from jenkins_jobs.formatter import deep_format
import jenkins_jobs.formatter
import jenkins_jobs.parser
import yaml

DESCRIPTION = """Migrate zuul v2 and Jenkins Job Builder to Zuul v3.

This program takes a zuul v2 layout.yaml and a collection of Jenkins Job
Builder job definitions and transforms them into a Zuul v3 config. An
optional mapping config can be given that defines how to map old jobs
to new jobs.
"""
def project_representer(dumper, data):
    return dumper.represent_mapping('tag:yaml.org,2002:map',
                                    data.items())


def construct_yaml_map(self, node):
    data = collections.OrderedDict()
    yield data
    value = self.construct_mapping(node)

    if isinstance(node, yaml.MappingNode):
        self.flatten_mapping(node)
    else:
        raise yaml.constructor.ConstructorError(
            None, None,
            'expected a mapping node, but found %s' % node.id,
            node.start_mark)

    mapping = collections.OrderedDict()
    for key_node, value_node in node.value:
        key = self.construct_object(key_node, deep=False)
        try:
            hash(key)
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                'while constructing a mapping', node.start_mark,
                'found unacceptable key (%s)' % exc, key_node.start_mark)
        value = self.construct_object(value_node, deep=False)
        mapping[key] = value
    data.update(mapping)


class IndentedEmitter(yaml.emitter.Emitter):
    def expect_block_sequence(self):
        self.increase_indent(flow=False, indentless=False)
        self.state = self.expect_first_block_sequence_item


class IndentedDumper(IndentedEmitter, yaml.serializer.Serializer,
                     yaml.representer.Representer, yaml.resolver.Resolver):
    def __init__(self, stream,
                 default_style=None, default_flow_style=None,
                 canonical=None, indent=None, width=None,
                 allow_unicode=None, line_break=None,
                 encoding=None, explicit_start=None, explicit_end=None,
                 version=None, tags=None):
        IndentedEmitter.__init__(
            self, stream, canonical=canonical,
            indent=indent, width=width,
            allow_unicode=allow_unicode,
            line_break=line_break)
        yaml.serializer.Serializer.__init__(
            self, encoding=encoding,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version, tags=tags)
        yaml.representer.Representer.__init__(
            self, default_style=default_style,
            default_flow_style=default_flow_style)
        yaml.resolver.Resolver.__init__(self)


def ordered_load(stream, *args, **kwargs):
    return yaml.load(stream=stream, *args, **kwargs)

def ordered_dump(data, stream=None, *args, **kwargs):
    return yaml.dump(data, stream=stream, default_flow_style=False,
                     Dumper=IndentedDumper, width=80, *args, **kwargs)

def get_single_key(var):
    if isinstance(var, str):
        return var
    elif isinstance(var, list):
        return var[0]
    return list(var.keys())[0]


def has_single_key(var):
    if isinstance(var, list):
        return len(var) == 1
    if isinstance(var, str):
        return True
    dict_keys = list(var.keys())
    if len(dict_keys) != 1:
        return False
    if var[get_single_key(from_dict)]:
        return False
    return True


def combination_matches(combination, match_combinations):
    """
    Checks if the given combination is matches for any of the given combination
    globs, being those a set of combinations where if a key is missing, it's
    considered matching

    (key1=2, key2=3)

    would match the combination match:
    (key2=3)

    but not:
    (key1=2, key2=2)
    """
    for cmatch in match_combinations:
        for key, val in combination.items():
            if cmatch.get(key, val) != val:
                break
        else:
            return True
    return False


def expandYamlForTemplateJob(self, project, template, jobs_glob=None):
    dimensions = []
    template_name = template['name']
    orig_template = copy.deepcopy(template)

    # reject keys that are not useful during yaml expansion
    for k in ['jobs']:
        project.pop(k)
    excludes = project.pop('exclude', [])
    for (k, v) in project.items():
        tmpk = '{{{0}}}'.format(k)
        if tmpk not in template_name:
            continue
        if type(v) == list:
            dimensions.append(zip([k] * len(v), v))
    # XXX somewhat hackish to ensure we actually have a single
    # pass through the loop
    if len(dimensions) == 0:
        dimensions = [(("", ""),)]

    for values in itertools.product(*dimensions):
        params = copy.deepcopy(project)
        params = self.applyDefaults(params, template)

        expanded_values = {}
        for (k, v) in values:
            if isinstance(v, dict):
                inner_key = next(iter(v))
                expanded_values[k] = inner_key
                expanded_values.update(v[inner_key])
            else:
                expanded_values[k] = v

        params.update(expanded_values)
        params = deep_format(params, params)
        if combination_matches(params, excludes):
            log = logging.getLogger("zuul.Migrate.YamlParser")
            log.debug('Excluding combination %s', str(params))
            continue

        allow_empty_variables = self.config \
            and self.config.has_section('job_builder') \
            and self.config.has_option(
                'job_builder', 'allow_empty_variables') \
            and self.config.getboolean(
                'job_builder', 'allow_empty_variables')

        for key in template.keys():
            if key not in params:
                params[key] = template[key]

        params['template-name'] = template_name
        expanded = deep_format(template, params, allow_empty_variables)

        job_name = expanded.get('name')
        if jobs_glob and not matches(job_name, jobs_glob):
            continue

        self.formatDescription(expanded)
        expanded['orig_template'] = orig_template
        expanded['template_name'] = template_name
        self.jobs.append(expanded)


jenkins_jobs.parser.YamlParser.expandYamlForTemplateJob = expandYamlForTemplateJob


class JJB(jenkins_jobs.builder.Builder):
    def __init__(self):
        self.global_config = None
        self._plugins_list = []

    def expandComponent(self, component_type, component, template_data):
        component_list_type = component_type + 's'
        new_components = []
        if isinstance(component, dict):
            name, component_data = next(iter(component.items()))
            if template_data:
                component_data = jenkins_jobs.formatter.deep_format(
                    component_data, template_data, True)
        else:
            name = component
            component_data = {}

        new_component = self.parser.data.get(component_type, {}).get(name)
        if new_component:
            for new_sub_component in new_component[component_list_type]:
                new_components.extend(
                    self.expandComponent(component_type,
                                         new_sub_component, component_data))
        else:
            new_components.append({name: component_data})
        return new_components

    def expandMacros(self, job):
        for component_type in ['builder', 'publisher', 'wrapper']:
            component_list_type = component_type + 's'
            new_components = []
            for new_component in job.get(component_list_type, []):
                new_components.extend(self.expandComponent(component_type,
                                                           new_component, {}))
            job[component_list_type] = new_components


class Job:

    def __init__(self,
                 orig: str,
                 name: str=None,
                 content: Dict[str, Any]=None,
                 vars: Dict[str, str]=None,
                 required_projects: List[str]=None,
                 nodes: List[str]=None,
                 parent=None) -> None:
        self.orig = orig
        self.voting = True
        self.name = name
        self.content = content.copy() if content else None
        self.vars = vars or {}
        self.required_projects = required_projects or []
        self.nodes = nodes or []
        self.parent = parent

        if self.content and not self.name:
            self.name = get_single_key(content)
        if not self.name:
            self.name = self.orig
        self.name = self.name.replace('-{name}', '').replace('{name}-', '')
        if self.orig.endswith('-nv'):
            self.voting = False
        if self.name.endswith('-nv'):
            # NOTE(mordred) This MIGHT not be safe - it's possible, although
            # silly, for someone to have -nv and normal versions of the same
            # job in the same pipeline. Let's deal with that if we find it
            # though.
            self.name = self.name.replace('-nv', '')

    def _stripNodeName(self, node):
        node_key = '-{node}'.format(node=node)
        self.name = self.name.replace(node_key, '')

    def setVars(self, vars):
        self.vars = vars

    def setRequiredProjects(self, required_projects):
        self.required_projects = required_projects

    def setParent(self, parent):
        self.parent = parent

    def extractNode(self, default_node, labels):
        matching_label = None
        for label in labels:
            if label in self.orig:
                if not matching_label:
                    matching_label = label
                elif len(label) > len(matching_label):
                    matching_label = label

        if matching_label:
            if matching_label == default_node:
                self._stripNodeName(matching_label)
            else:
                self.nodes.append(matching_label)

    def getDepends(self):
        return [self.parent.name]

    def getNodes(self):
        return self.nodes

    def toDict(self):
        if self.content:
            output = self.content
        else:
            output = collections.OrderedDict()
            output[self.name] = collections.OrderedDict()

        if self.parent:
            output[self.name].setdefault('dependencies', self.getDepends())

        if not self.voting:
            output[self.name].setdefault('voting', False)

        if self.nodes:
            output[self.name].setdefault('nodes', self.getNodes())

        if self.required_projects:
            output[self.name].setdefault(
                'required-projects', self.required_projects)

        if self.vars:
            job_vars = output[self.name].get('vars', collections.OrderedDict())
            job_vars.update(self.vars)

        if not output[self.name]:
            return self.name
        return output


class JobMapping:
    log = logging.getLogger("zuul.Migrate.JobMapping")

    def __init__(self, nodepool_config, mapping_file=None):
        self.job_direct = {}
        self.labels = []
        self.job_mapping = []
        self.template_mapping = {}
        nodepool_data = ordered_load(open(nodepool_config, 'r'))
        for label in nodepool_data['labels']:
            self.labels.append(label['name'])
        if not mapping_file:
            self.default_node = 'ubuntu-xenial'
        else:
            mapping_data = ordered_load(open(mapping_file, 'r'))
            self.default_node = mapping_data['default-node']
            for map_info in mapping_data.get('job-mapping', []):
                if map_info['old'].startswith('^'):
                    map_info['pattern'] = re.compile(map_info['old'])
                    self.job_mapping.append(map_info)
                else:
                    self.job_direct[map_info['old']] = map_info['new']

            for map_info in mapping_data.get('template-mapping', []):
                self.template_mapping[map_info['old']] = map_info['new']

    def makeNewName(self, new_name, match_dict):
        return new_name.format(**match_dict)

    def hasProjectTemplate(self, old_name):
        return old_name in self.template_mapping

    def getNewTemplateName(self, old_name):
        return self.template_mapping.get(old_name, old_name)

    def mapNewJob(self, name, info) -> Optional[Job]:
        matches = info['pattern'].search(name)
        if not matches:
            return None
        match_dict = matches.groupdict()
        if isinstance(info['new'], dict):
            job = Job(orig=name, content=info['new'])
        else:
            job = Job(orig=name, name=info['new'].format(**match_dict))

        if 'vars' in info:
            job.setVars(self._expandVars(info, match_dict))

        if 'required-projects' in info:
            job.setRequiredProjects(
                self._expandRequiredProjects(info, match_dict))
        return job

    def _expandVars(self, info, match_dict):
        job_vars = info['vars'].copy()
        for key in job_vars.keys():
            job_vars[key] = job_vars[key].format(**match_dict)
        return job_vars

    def _expandRequiredProjects(self, info, match_dict):
        required_projects = []
        job_projects = info['required-projects'].copy()
        for project in job_projects:
            required_projects.append(project.format(**match_dict))
        return required_projects

    def getNewJob(self, job_name, remove_gate):
        if job_name in self.job_direct:
            if isinstance(self.job_direct[job_name], dict):
                return Job(job_name, content=self.job_direct[job_name])
            else:
                return Job(job_name, name=self.job_direct[job_name])

        new_job = None
        for map_info in self.job_mapping:
            new_job = self.mapNewJob(job_name, map_info)
            if new_job:
                break
        if not new_job:
            if remove_gate:
                job_name = job_name.replace('gate-', '', 1)
            job_name = 'legacy-{job_name}'.format(job_name=job_name)
            new_job = Job(orig=job_name, name=job_name)

        new_job.extractNode(self.default_node, self.labels)
        return new_job


class ZuulMigrate:

    log = logging.getLogger("zuul.Migrate")

    def __init__(self, layout, job_config, nodepool_config,
                 outdir, mapping, move):
        self.layout = ordered_load(open(layout, 'r'))
        self.job_config = job_config
        self.outdir = outdir
        self.mapping = JobMapping(nodepool_config, mapping)
        self.move = move

        self.jobs = {}

    def run(self):
        self.loadJobs()
        self.convertJobs()
        self.writeJobs()

    def loadJobs(self):
        self.log.debug("Loading jobs")
        builder = JJB()
        builder.load_files([self.job_config])
        builder.parser.expandYaml()
        unseen = set(self.jobs.keys())
        for job in builder.parser.jobs:
            builder.expandMacros(job)
            self.jobs[job['name']] = job
            unseen.discard(job['name'])
        for name in unseen:
            del self.jobs[name]

    def convertJobs(self):
        pass

    def setupDir(self):
        zuul_yaml = os.path.join(self.outdir, 'zuul.yaml')
        zuul_d = os.path.join(self.outdir, 'zuul.d')
        orig = os.path.join(zuul_d, '01zuul.yaml')
        outfile = os.path.join(zuul_d, '99converted.yaml')
        if not os.path.exists(self.outdir):
            os.makedirs(self.outdir)
        if not os.path.exists(zuul_d):
            os.makedirs(zuul_d)
        if os.path.exists(zuul_yaml) and self.move:
            os.rename(zuul_yaml, orig)
        return outfile

    def makeNewJobs(self, old_job, parent: Job=None):
        self.log.debug("makeNewJobs(%s)", old_job)
        if isinstance(old_job, str):
            remove_gate = True
            if old_job.startswith('gate-'):
                # Check to see if gate- and bare versions exist
                if old_job.replace('gate-', '', 1) in self.jobs:
                    remove_gate = False
            job = self.mapping.getNewJob(old_job, remove_gate)
            if parent:
                job.setParent(parent)
            return [job]

        new_list = []  # type: ignore
        if isinstance(old_job, list):
            for job in old_job:
                new_list.extend(self.makeNewJobs(job, parent=parent))

        elif isinstance(old_job, dict):
            parent_name = get_single_key(old_job)
            parent = Job(orig=parent_name, parent=parent)

            jobs = self.makeNewJobs(old_job[parent_name], parent=parent)
            for job in jobs:
                new_list.append(job)
            new_list.append(parent)
        return new_list

    def writeProjectTemplate(self, template):
        new_template = collections.OrderedDict()
        if 'name' in template:
            new_template['name'] = template['name']
        for key, value in template.items():
            if key == 'name':
                continue
            jobs = [job.toDict() for job in self.makeNewJobs(value)]
            new_template[key] = dict(jobs=jobs)

        return new_template

    def writeProject(self, project):
        new_project = collections.OrderedDict()
        if 'name' in project:
            new_project['name'] = project['name']
        if 'template' in project:
            new_project['template'] = []
            for template in project['template']:
                new_project['template'].append(dict(
                    name=self.mapping.getNewTemplateName(template['name'])))
        for key, value in project.items():
            if key in ('name', 'template'):
                continue
            else:
                jobs = [job.toDict() for job in self.makeNewJobs(value)]
                new_project[key] = dict(jobs=jobs)

        return new_project

    def writeJobs(self):
        outfile = self.setupDir()
        config = []

        for template in self.layout.get('project-templates', []):
            self.log.debug("Processing template: %s", template)
            if not self.mapping.hasProjectTemplate(template['name']):
                config.append(
                    {'project-template': self.writeProjectTemplate(template)})

        for project in self.layout.get('projects', []):
            config.append(
                {'project': self.writeProject(project)})

        with open(outfile, 'w') as yamlout:
            # Insert an extra space between top-level list items
            yamlout.write(ordered_dump(config).replace('\n-', '\n\n-'))


def main():
    yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                         construct_yaml_map)

    yaml.add_representer(collections.OrderedDict, project_representer,
                         Dumper=IndentedDumper)

    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        'layout',
        help="The Zuul v2 layout.yaml file to read.")
    parser.add_argument(
        'job_config',
        help="Directory containing Jenkins Job Builder job definitions.")
    parser.add_argument(
        'nodepool_config',
        help="Nodepool config file containing complete set of node names")
    parser.add_argument(
        'outdir',
        help="A directory into which the Zuul v3 config will be written.")
    parser.add_argument(
        '--mapping',
        default=None,
        help="A filename with a yaml mapping of old name to new name.")
    parser.add_argument(
        '-v', dest='verbose', action='store_true', help='verbose output')
    parser.add_argument(
        '-m', dest='move', action='store_true',
        help='Move zuul.yaml to zuul.d if it exists')

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    ZuulMigrate(args.layout, args.job_config, args.nodepool_config,
                args.outdir, args.mapping, args.move).run()


if __name__ == '__main__':
    main()
