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
import getopt
import logging
import os
import subprocess
import tempfile
import re
from typing import Any, Dict, List, Optional  # flake8: noqa

import jenkins_jobs.builder
from jenkins_jobs.formatter import deep_format
import jenkins_jobs.formatter
from jenkins_jobs.parser import matches
import jenkins_jobs.parser
import yaml

JOBS_BY_ORIG_TEMPLATE = {}  # type: ignore
SUFFIXES = []  # type: ignore
ENVIRONMENT = '{{ host_vars[inventory_hostname] | zuul_legacy_vars }}'
DESCRIPTION = """Migrate zuul v2 and Jenkins Job Builder to Zuul v3.

This program takes a zuul v2 layout.yaml and a collection of Jenkins Job
Builder job definitions and transforms them into a Zuul v3 config. An
optional mapping config can be given that defines how to map old jobs
to new jobs.
"""

def deal_with_shebang(data):
    # Ansible shell blocks do not honor shebang lines. That's fine - but
    # we do have a bunch of scripts that have either nothing, -x, -xe,
    # -ex or -eux. Transform those into leading set commands
    if not data.startswith('#!'):
        return (None, data)
    data_lines = data.split('\n')
    data_lines.reverse()
    shebang = data_lines.pop()
    split_line = shebang.split()
    # Strip the # and the !
    executable = split_line[0][2:]
    if executable == '/bin/sh':
        # Ansible default
        executable = None
    if len(split_line) > 1:
        flag_x = False
        flag_e = False
        flag_u = False
        optlist, args = getopt.getopt(split_line[1:], 'uex')
        for opt, _ in optlist:
            if opt == '-x':
                flag_x = True
            elif opt == '-e':
                flag_e = True
            elif opt == '-u':
                flag_u = True

        if flag_x:
            data_lines.append('set -x')
        if flag_e:
            data_lines.append('set -e')
        if flag_u:
            data_lines.append('set -u')
    data_lines.reverse()
    data = '\n'.join(data_lines).lstrip()
    return (executable, data)


def extract_projects(data):
    # export PROJECTS="openstack/blazar $PROJECTS"
    # export DEVSTACK_PROJECT_FROM_GIT=python-swiftclient
    # export DEVSTACK_PROJECT_FROM_GIT="python-octaviaclient"
    # export DEVSTACK_PROJECT_FROM_GIT+=",glean"
    projects = []
    data_lines = data.split('\n')
    for line in data_lines:
        line = line.strip().replace('"', '').replace('+', '').replace(',', ' ')
        if (line.startswith('export PROJECTS') or
                line.startswith('export DEVSTACK_PROJECT_FROM_GIT')):
            nothing, project_string = line.split('=')
            project_string = project_string.replace('$PROJECTS', '').strip()
            projects.extend(project_string.split())
    return projects


def expand_project_names(required, full):
    projects = []
    for name in full:
        org, repo = name.split('/')
        if repo in required or name in required:
            projects.append(name)
    return projects


# from :
# http://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data  flake8: noqa
def should_use_block(value):
    for c in u"\u000a\u000d\u001c\u001d\u001e\u0085\u2028\u2029":
        if c in value:
            return True
    return False


def my_represent_scalar(self, tag, value, style=None):
    if style is None:
        if should_use_block(value):
             style='|'
        else:
            style = self.default_style

    node = yaml.representer.ScalarNode(tag, value, style=style)
    if self.alias_key is not None:
        self.represented_objects[self.alias_key] = node
    return node

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
    dumper = IndentedDumper
    # We need to do this because of how template expasion into a project
    # works. Without it, we end up with YAML references to the expanded jobs.
    dumper.ignore_aliases = lambda self, data: True

    output = yaml.dump(
        data, default_flow_style=False,
        Dumper=dumper, width=80, *args, **kwargs).replace(
            '\n    -', '\n\n    -')
    if stream:
        stream.write(output)
    else:
        return output


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
    if var[get_single_key(var)]:
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
        project_name = params['name']
        params['name'] = '$ZUUL_SHORT_PROJECT_NAME'
        expanded = deep_format(template, params, allow_empty_variables)

        job_name = expanded.get('name')
        templated_job_name = job_name
        if job_name:
            job_name = job_name.replace(
                '$ZUUL_SHORT_PROJECT_NAME', project_name)
            expanded['name'] = job_name
        if jobs_glob and not matches(job_name, jobs_glob):
            continue

        self.formatDescription(expanded)
        expanded['orig_template'] = orig_template
        expanded['template_name'] = template_name
        self.jobs.append(expanded)
        JOBS_BY_ORIG_TEMPLATE[templated_job_name] = expanded

jenkins_jobs.parser.YamlParser.expandYamlForTemplateJob = \
    expandYamlForTemplateJob


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


class OldProject:
    def __init__(self, name, gate_jobs):
        self.name = name
        self.gate_jobs = gate_jobs


class OldJob:
    def __init__(self, name):
        self.name = name
        self.queue_name = None

    def __repr__(self):
        return self.name


class Job:

    log = logging.getLogger("zuul.Migrate")

    def __init__(self,
                 orig: str,
                 name: str=None,
                 content: Dict[str, Any]=None,
                 vars: Dict[str, str]=None,
                 nodes: List[str]=None,
                 parent=None) -> None:
        self.orig = orig
        self.voting = True
        self.name = name
        self.content = content.copy() if content else None
        self.vars = vars or {}
        self.required_projects = []  # type: ignore
        self.nodes = nodes or []
        self.parent = parent
        self.branch = None
        self.files = None
        self.jjb_job = None
        self.emit = True

        if self.content and not self.name:
            self.name = get_single_key(content)
        if not self.name:
            self.name = self.orig
        self.name = self.name.replace('-{name}', '').replace('{name}-', '')

        for suffix in SUFFIXES:
            suffix = '-{suffix}'.format(suffix=suffix)

            if self.name.endswith(suffix):
                self.name = self.name.replace(suffix, '')

    def _stripNodeName(self, node):
        node_key = '-{node}'.format(node=node)
        self.name = self.name.replace(node_key, '')

    def setNoEmit(self):
        self.emit = False

    def setVars(self, vars):
        self.vars = vars

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

    def addJJBJob(self, jobs):
        if '{name}' in self.orig:
            self.jjb_job = JOBS_BY_ORIG_TEMPLATE[self.orig.format(
                name='$ZUUL_SHORT_PROJECT_NAME')]
        else:
            self.jjb_job = jobs[self.orig]

    def getTimeout(self):
        if self.jjb_job:
            for wrapper in self.jjb_job.get('wrappers', []):
                if isinstance(wrapper, dict):
                    build_timeout = wrapper.get('timeout')
                    if isinstance(build_timeout, dict):
                        timeout = build_timeout.get('timeout')
                        if timeout is not None:
                            timeout = int(timeout) * 60

    @property
    def short_name(self):
        return self.name.replace('legacy-', '')

    @property
    def job_path(self):
        return 'playbooks/legacy/{name}'.format(name=self.short_name)

    def _getRsyncOptions(self, source):
        # If the source starts with ** then we want to match any
        # number of directories, so don't anchor the include filter.
        # If it does not start with **, then the intent is likely to
        # at least start by matching an immediate file or subdirectory
        # (even if later we have a ** in the middle), so in this case,
        # anchor it to the root of the transfer (the workspace).
        if not source.startswith('**'):
            source = os.path.join('/', source)
        # These options mean: include the thing we want, include any
        # directories (so that we continue to search for the thing we
        # want no matter how deep it is), exclude anything that
        # doesn't match the thing we want or is a directory, then get
        # rid of empty directories left over at the end.
        rsync_opts = ['--include="%s"' % source,
                      '--include="*/"',
                      '--exclude="*"',
                      '--prune-empty-dirs']
        return rsync_opts

    def _makeSCPTask(self, publisher):
        # NOTE(mordred) About docs-draft manipulation:
        # The target of html/ was chosen to put the node contents into the
        # html dir inside of logs such that if the node's contents have an
        # index.html in them setting the success-url to html/ will render
        # things as expected. Existing builder macros look like:
        # 
        #   - publisher:
        #     name: upload-sphinx-draft
        #     publishers:
        #       - scp:
        #           site: 'static.openstack.org'
        #           files:
        #             - target: 'docs-draft/$LOG_PATH'
        #               source: 'doc/build/html/**'
        #               keep-hierarchy: true
        #               copy-after-failure: true
        #
        # Which is pulling the tree of the remote html directory starting with
        # doc/build/html and putting that whole thing into
        # docs-draft/$LOG_PATH.
        #
        # Then there is a success-pattern in layout.yaml that looks like:
        # 
        #     http://{url}/{log_path}/doc/build/html/
        #
        # Which gets reports. There are many variations on that URL. So rather
        # than needing to figure out varying success-urls to report in v3,
        # we'll remote the ** and not process this through the rsync_opts
        # processing we use for the other publishers, but instead will just
        # pass doc/build/html/ to get the contents of doc/build/html/ and we'll
        # put those in {{ log_root }}/html/ locally meaning the success-url
        # can always be html/. This should work for all values of source
        # from v2.
        tasks = []
        artifacts = False
        draft = False
        site = publisher['scp']['site']
        for scpfile in publisher['scp']['files']:
            if 'ZUUL_PROJECT' in scpfile.get('source', ''):
                self.log.error(
                    "Job {name} uses ZUUL_PROJECT in source".format(
                        name=self.name))
                continue

            if scpfile.get('copy-console'):
                continue
            else:
                src = "{{ ansible_user_dir }}"
                rsync_opts = self._getRsyncOptions(scpfile['source'])

            target = scpfile['target']
            # TODO(mordred) Generalize this next section, it's SUPER
            # openstack specific. We can likely do this in mapping.yaml
            if site == 'static.openstack.org':
                for f in ('service-types', 'specs'):
                    if target.startswith(f):
                        self.log.error(
                            "Job {name} uses {f} publishing".format(
                                name=self.name, f=f))
                        continue
                if target.startswith('docs-draft'):
                    target = "{{ zuul.executor.log_root }}/html/"
                    src = scpfile['source'].replace('**', '')
                    rsync_opts = None
                    draft = True
            elif site == 'tarballs.openstack.org':
                if not target.startswith('tarballs'):
                    self.log.error(
                        'Job {name} wants to publish artifacts to non'
                        ' tarballs dir'.format(name=self.name))
                    continue
                if target.startswith('tarballs/ci'):
                    target = target.split('/', 3)[-1]
                else:
                    target = target.split('/', 2)[-1]
                target = "{{ zuul.executor.work_root }}/artifacts/" + target
                artifacts = True
            elif site == 'yaml2ical':
                self.log.error('Job {name} uses yaml2ical publisher')
                continue

            syncargs = collections.OrderedDict()
            syncargs['src'] = src
            syncargs['dest'] = target
            syncargs['copy_links'] = 'yes'
            syncargs['mode'] = 'pull'
            syncargs['verify_host'] = True
            if rsync_opts:
                syncargs['rsync_opts'] = rsync_opts
            task = collections.OrderedDict()
            task['name'] = 'copy files from {src} on node to'.format(src=src)
            task['synchronize'] = syncargs
            # We don't use retry_args here because there is a bug in
            # the synchronize module that breaks subsequent attempts at
            # retrying. Better to try once and get an accurate error
            # message if it fails.
            # https://github.com/ansible/ansible/issues/18281
            tasks.append(task)

        if artifacts:
            ensure_task = collections.OrderedDict()
            ensure_task['name'] = 'Ensure artifacts directory exists'
            ensure_task['file'] = collections.OrderedDict(
                path="{{ zuul.executor.work_root }}/artifacts",
                state='directory')
            ensure_task['delegate_to'] = 'localhost'
            tasks.insert(0, ensure_task)
        return dict(tasks=tasks, artifacts=artifacts, draft=draft)

    def _emitShellTask(self, data, syntax_check):
        shell, data = deal_with_shebang(data)
        task = collections.OrderedDict()
        task['shell'] = data
        if shell:
            task['args'] = dict(executable=shell)

        if syntax_check:
            # Emit a test playbook with this shell task in it then run
            # ansible-playbook --syntax-check on it. This will fail if there
            # are embedding issues, such as with unbalanced single quotes
            # The end result should be less scripts and more shell
            play = dict(hosts='all', tasks=[task])
            (fd, tmp_path) = tempfile.mkstemp()
            try:
                f = os.fdopen(fd, 'w')
                ordered_dump([play], f)
                f.close()
                proc = subprocess.run(
                    ['ansible-playbook', '--syntax-check', tmp_path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if proc.returncode != 0:
                    # Return of None means we must emit a script
                    self.log.error(
                        "Job {name} had an ansible syntax error, using script"
                        " instead of shell".format(name=self.name))
                    return None
            finally:
                os.unlink(tmp_path)
        return task

    def _emitScriptContent(self, data, playbook_dir, seq):
        script_fn = '%s-%02d.sh' % (self.short_name, seq)
        script_path = os.path.join(playbook_dir, script_fn)

        with open(script_path, 'w') as script:
            if not data.startswith('#!'):
                data = '#!/bin/bash -x\n %s' % (data,)
            script.write(data)

        task = collections.OrderedDict()
        task['name'] = 'Running playbooks/legacy/{playbook}'.format(
            playbook=script_fn)
        task['script'] = script_fn
        return task

    def _makeBuilderTask(self, playbook_dir, builder, sequence, syntax_check):
        # Don't write a script to echo the template line
        # TODO(mordred) Put these into mapping.yaml
        if builder['shell'].startswith('echo JJB template: '):
            return
        if 'echo "Detailed logs:' in builder['shell']:
            return

        task = self._emitShellTask(builder['shell'], syntax_check)
        if not task:
            task = self._emitScriptContent(
                builder['shell'], playbook_dir, sequence)
        task['environment'] = ENVIRONMENT
        return task

    def _transformPublishers(self, jjb_job):
        early_publishers = []
        late_publishers = []
        old_publishers = jjb_job.get('publishers', [])
        for publisher in old_publishers:
            early_scpfiles = []
            late_scpfiles = []
            if 'scp' not in publisher:
                early_publishers.append(publisher)
                continue
            copy_console = False
            for scpfile in publisher['scp']['files']:
                if scpfile.get('copy-console'):
                    scpfile['keep-hierarchy'] = True
                    late_scpfiles.append(scpfile)
                    copy_console = True
                else:
                    early_scpfiles.append(scpfile)
            publisher['scp']['files'] = early_scpfiles + late_scpfiles
            if copy_console:
                late_publishers.append(publisher)
            else:
                early_publishers.append(publisher)
        publishers = early_publishers + late_publishers
        if old_publishers != publishers:
            self.log.debug("Transformed job publishers")
        return early_publishers, late_publishers

    def emitPlaybooks(self, jobsdir, syntax_check=False):
        has_artifacts = False
        has_draft = False
        if not self.jjb_job:
            if self.emit:
                self.log.error(
                    'Job {name} has no job content'.format(name=self.name))
            return False, False, False

        playbook_dir = os.path.join(jobsdir, self.job_path)
        if not os.path.exists(playbook_dir):
            os.makedirs(playbook_dir)

        run_playbook = os.path.join(self.job_path, 'run.yaml')
        post_playbook = os.path.join(self.job_path, 'post.yaml')
        tasks = []
        sequence = 0
        for builder in self.jjb_job.get('builders', []):
            if 'shell' in builder:
                self.required_projects.extend(
                    extract_projects(builder['shell']))
                task = self._makeBuilderTask(
                    playbook_dir, builder, sequence, syntax_check)
                if task:
                    if 'script' in task:
                        sequence += 1
                    tasks.append(task)
        play = collections.OrderedDict()
        play['hosts'] = 'all'
        play['name'] = 'Autoconverted job {name} from old job {old}'.format(
            name=self.name, old=self.orig)
        play['tasks'] = tasks

        with open(run_playbook, 'w') as run_playbook_out:
            ordered_dump([play], run_playbook_out)

        has_post = False
        tasks = []
        early_publishers, late_publishers = self._transformPublishers(
            self.jjb_job)
        for publishers in [early_publishers, late_publishers]:
            for publisher in publishers:
                if 'scp' in publisher:
                    ret = self._makeSCPTask(publisher)
                    if ret['artifacts']:
                        has_artifacts = True
                    if ret['draft']:
                        has_draft = True
                    tasks.extend(ret['tasks'])
                if 'afs' in builder:
                    self.log.error(
                        "Job {name} uses AFS publisher".format(name=self.name))
        if tasks:
            has_post = True
            play = collections.OrderedDict()
            play['hosts'] = 'all'
            play['tasks'] = tasks
            with open(post_playbook, 'w') as post_playbook_out:
                ordered_dump([play], post_playbook_out)
        return has_artifacts, has_post, has_draft

    def toJobDict(
            self, has_artifacts=False, has_post=False, has_draft=False,
            project_names=[]):
        output = collections.OrderedDict()
        output['name'] = self.name
        if has_artifacts:
            output['parent'] = 'publish-openstack-artifacts'
        elif has_draft:
            output['success-url'] = 'html/'
        output['run'] = os.path.join(self.job_path, 'run.yaml')
        if has_post:
            output['post-run'] = os.path.join(self.job_path, 'post.yaml')

        if self.vars:
            output['vars'] = self.vars.copy()
        timeout = self.getTimeout()
        if timeout:
            output['timeout'] = timeout
            output['vars']['BUILD_TIMEOUT'] = str(timeout * 1000)

        if self.nodes:
            output['nodes'] = self.getNodes()

        if self.required_projects:
            output['required-projects'] = expand_project_names(
                self.required_projects, project_names)

        return output

    def toPipelineDict(self):
        if self.content:
            output = self.content
        else:
            output = collections.OrderedDict()
            output[self.name] = collections.OrderedDict()

        if self.parent:
            output[self.name].setdefault('dependencies', self.getDepends())

        if not self.voting:
            output[self.name].setdefault('voting', False)

        if self.vars:
            job_vars = output[self.name].get('vars', collections.OrderedDict())
            job_vars.update(self.vars)

        if self.branch:
            output[self.name]['branch'] = self.branch

        if self.files:
            output[self.name]['files'] = self.files

        if not output[self.name]:
            return self.name

        return output


class JobMapping:
    log = logging.getLogger("zuul.Migrate.JobMapping")

    def __init__(self, nodepool_config, layout, mapping_file=None):
        self.layout = layout
        self.job_direct = {}
        self.labels = []
        self.job_mapping = []
        self.template_mapping = {}
        self.jjb_jobs = {}
        self.seen_new_jobs = []
        self.unshare = []
        nodepool_data = ordered_load(open(nodepool_config, 'r'))
        for label in nodepool_data['labels']:
            self.labels.append(label['name'])
        if not mapping_file:
            self.default_node = 'ubuntu-xenial'
        else:
            mapping_data = ordered_load(open(mapping_file, 'r'))
            self.default_node = mapping_data['default-node']
            global SUFFIXES
            SUFFIXES = mapping_data.get('strip-suffixes', [])
            self.unshare = mapping_data.get('unshare', [])
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

    def setJJBJobs(self, jjb_jobs):
        self.jjb_jobs = jjb_jobs

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

        return job

    def _expandVars(self, info, match_dict):
        job_vars = info['vars'].copy()
        for key in job_vars.keys():
            job_vars[key] = job_vars[key].format(**match_dict)
        return job_vars

    def getNewJob(self, job_name, remove_gate):
        if job_name in self.job_direct:
            if isinstance(self.job_direct[job_name], dict):
                job = Job(job_name, content=self.job_direct[job_name])
            else:
                job = Job(job_name, name=self.job_direct[job_name])
            if job_name not in self.seen_new_jobs:
                self.seen_new_jobs.append(self.job_direct[job_name])
            job.setNoEmit()
            return job

        new_job = None
        for map_info in self.job_mapping:
            new_job = self.mapNewJob(job_name, map_info)
            if new_job:
                if job_name not in self.seen_new_jobs:
                    self.seen_new_jobs.append(new_job.name)
                new_job.setNoEmit()
                break
        if not new_job:
            orig_name = job_name
            if remove_gate:
                job_name = job_name.replace('gate-', '', 1)
            job_name = 'legacy-{job_name}'.format(job_name=job_name)
            new_job = Job(orig=orig_name, name=job_name)

        new_job.extractNode(self.default_node, self.labels)

        # Handle matchers
        for layout_job in self.layout.get('jobs', []):
            if re.search(layout_job['name'], new_job.orig):
                # Matchers that can apply to templates must be processed first
                # since project-specific matchers can cause the template to
                # be expanded into a project.
                if not layout_job.get('voting', True):
                    new_job.voting = False
                if layout_job.get('branch'):
                    new_job.branch = layout_job['branch']
                if layout_job.get('files'):
                    new_job.files = layout_job['files']

        new_job.addJJBJob(self.jjb_jobs)
        return new_job


class ChangeQueue:
    def __init__(self):
        self.name = ''
        self.assigned_name = None
        self.generated_name = None
        self.projects = []
        self._jobs = set()

    def getJobs(self):
        return self._jobs

    def getProjects(self):
        return [p.name for p in self.projects]

    def addProject(self, project):
        if project not in self.projects:
            self.projects.append(project)
            self._jobs |= project.gate_jobs

            names = [x.name for x in self.projects]
            names.sort()
            self.generated_name = names[0].split('/')[-1]

            for job in self._jobs:
                if job.queue_name:
                    if (self.assigned_name and
                            job.queue_name != self.assigned_name):
                        raise Exception("More than one name assigned to "
                                        "change queue: %s != %s" %
                                        (self.assigned_name,
                                         job.queue_name))
                    self.assigned_name = job.queue_name
            self.name = self.assigned_name or self.generated_name

    def mergeChangeQueue(self, other):
        for project in other.projects:
            self.addProject(project)


class ZuulMigrate:

    log = logging.getLogger("zuul.Migrate")

    def __init__(self, layout, job_config, nodepool_config,
                 outdir, mapping, move, syntax_check):
        self.layout = ordered_load(open(layout, 'r'))
        self.job_config = job_config
        self.outdir = outdir
        self.mapping = JobMapping(nodepool_config, self.layout, mapping)
        self.move = move
        self.syntax_check = syntax_check

        self.jobs = {}
        self.old_jobs = {}
        self.job_objects = []
        self.new_templates = {}

    def run(self):
        self.loadJobs()
        self.buildChangeQueues()
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
        self.mapping.setJJBJobs(self.jobs)

    def getOldJob(self, name):
        if name not in self.old_jobs:
            self.old_jobs[name] = OldJob(name)
        return self.old_jobs[name]

    def flattenOldJobs(self, tree, name=None):
        if isinstance(tree, str):
            n = tree.format(name=name)
            if n in self.mapping.unshare:
                return []
            return [self.getOldJob(n)]

        new_list = []  # type: ignore
        if isinstance(tree, list):
            for job in tree:
                new_list.extend(self.flattenOldJobs(job, name))
        elif isinstance(tree, dict):
            parent_name = get_single_key(tree)
            jobs = self.flattenOldJobs(tree[parent_name], name)
            for job in jobs:
                if job not in self.mapping.unshare:
                    new_list.append(self.getOldJob(job))
            if parent_name not in self.mapping.unshare:
                new_list.append(self.getOldJob(parent_name))
        return new_list

    def buildChangeQueues(self):
        self.log.debug("Building shared change queues")

        for j in self.layout['jobs']:
            if '^' in j['name'] or '$' in j['name']:
                continue
            job = self.getOldJob(j['name'])
            job.queue_name = j.get('queue-name')

        change_queues = []

        for project in self.layout.get('projects'):
            if 'gate' not in project:
                continue
            gate_jobs = set()
            for template in project['template']:
                for pt in self.layout.get('project-templates'):
                    if pt['name'] != template['name']:
                        continue
                    if 'gate' not in pt['name']:
                        continue
                    gate_jobs |= set(self.flattenOldJobs(pt['gate'],
                                                         project['name']))
            gate_jobs |= set(self.flattenOldJobs(project['gate']))
            old_project = OldProject(project['name'], gate_jobs)
            change_queue = ChangeQueue()
            change_queue.addProject(old_project)
            change_queues.append(change_queue)
            self.log.debug("Created queue: %s" % change_queue)

        # Iterate over all queues trying to combine them, and keep doing
        # so until they can not be combined further.
        last_change_queues = change_queues
        while True:
            new_change_queues = self.combineChangeQueues(last_change_queues)
            if len(last_change_queues) == len(new_change_queues):
                break
            last_change_queues = new_change_queues

        self.log.debug("  Shared change queues:")
        for queue in new_change_queues:
            self.log.debug("    %s containing %s" % (
                queue, queue.generated_name))
        self.change_queues = new_change_queues

    def combineChangeQueues(self, change_queues):
        self.log.debug("Combining shared queues")
        new_change_queues = []
        for a in change_queues:
            merged_a = False
            for b in new_change_queues:
                if not a.getJobs().isdisjoint(b.getJobs()):
                    self.log.debug("Merging queue %s into %s" % (a, b))
                    b.mergeChangeQueue(a)
                    merged_a = True
                    break  # this breaks out of 'for b' and continues 'for a'
            if not merged_a:
                self.log.debug("Keeping queue %s" % (a))
                new_change_queues.append(a)
        return new_change_queues

    def convertJobs(self):
        pass

    def setupDir(self):
        zuul_yaml = os.path.join(self.outdir, 'zuul.yaml')
        zuul_d = os.path.join(self.outdir, 'zuul.d')
        orig = os.path.join(zuul_d, '01zuul.yaml')
        job_outfile = os.path.join(zuul_d, '99converted-jobs.yaml')
        project_outfile = os.path.join(zuul_d, '99converted-projects.yaml')
        if not os.path.exists(self.outdir):
            os.makedirs(self.outdir)
        if not os.path.exists(zuul_d):
            os.makedirs(zuul_d)
        if os.path.exists(zuul_yaml) and self.move:
            os.rename(zuul_yaml, orig)
        return job_outfile, project_outfile

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
            parent = self.makeNewJobs(parent_name, parent=parent)[0]

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

            # keep a cache of the Job objects so we can use it to get old
            # job name to new job name when expanding templates into projects.
            tmp = [job for job in self.makeNewJobs(value)]
            self.job_objects.extend(tmp)
            jobs = [job.toPipelineDict() for job in tmp]
            new_template[key] = dict(jobs=jobs)

        return new_template

    def scanForProjectMatchers(self, project_name):
        ''' Get list of job matchers that reference the given project name '''
        job_matchers = []
        for matcher in self.layout.get('jobs', []):
            for skipper in matcher.get('skip-if', []):
                if skipper.get('project'):
                    if re.search(skipper['project'], project_name):
                        job_matchers.append(matcher)
        return job_matchers

    def findReferencedTemplateNames(self, job_matchers, project_name):
        ''' Search templates in the layout file for matching jobs '''
        template_names = []

        def search_jobs(template):
            def _search(job):
                if isinstance(job, str):
                    for matcher in job_matchers:
                        if re.search(matcher['name'],
                                     job.format(name=project_name)):
                            template_names.append(template['name'])
                            return True
                elif isinstance(job, list):
                    for i in job:
                        if _search(i):
                            return True
                elif isinstance(job, dict):
                    for k, v in job.items():
                        if _search(k) or _search(v):
                            return True
                return False

            for key, value in template.items():
                if key == 'name':
                    continue
                for job in template[key]:
                    if _search(job):
                        return

        for template in self.layout.get('project-templates', []):
            search_jobs(template)
        return template_names

    def expandTemplateIntoProject(self, template_name, project):
        self.log.debug("EXPAND template %s into project %s",
                       template_name, project['name'])
        # find the new template since that's the thing we're expanding
        if template_name not in self.new_templates:
            self.log.error(
                "Template %s not found for expansion into project %s",
                template_name, project['name'])
            return

        template = self.new_templates[template_name]

        for pipeline, value in template.items():
            if pipeline == 'name':
                continue
            if pipeline not in project:
                project[pipeline] = dict(jobs=[])
            project[pipeline]['jobs'].extend(value['jobs'])

    def getOldJobName(self, new_job_name):
        for job in self.job_objects:
            if job.name == new_job_name:
                return job.orig
        return None

    def applyProjectMatchers(self, matchers, project):
        '''
        Apply per-project job matchers to the given project.

        :param matchers: Job matchers that referenced the given project.
        :param project: The new project object.
        '''

        def processPipeline(pipeline_jobs, job_name_regex, files):
            for job in pipeline_jobs:
                if isinstance(job, str):
                    old_job_name = self.getOldJobName(job)
                    if not old_job_name:
                        continue
                    if re.search(job_name_regex, old_job_name):
                        self.log.debug(
                            "Applied irrelevant-files to job %s in project %s",
                            job, project['name'])
                        job = dict(job={'irrelevant-files': files})
                elif isinstance(job, dict):
                    # should really only be one key (job name)
                    job_name = list(job.keys())[0]
                    extras = job[job_name]
                    old_job_name = self.getOldJobName(job_name)
                    if not old_job_name:
                        continue
                    if re.search(job_name_regex, old_job_name):
                        self.log.debug(
                            "Applied irrelevant-files to complex job "
                            "%s in project %s", job_name, project['name'])
                        if 'irrelevant-files' not in extras:
                            extras['irrelevant-files'] = []
                        extras['irrelevant-files'].extend(files)

        def applyIrrelevantFiles(job_name_regex, files):
            for k, v in project.items():
                if k in ('template', 'name'):
                    continue
                processPipeline(project[k]['jobs'], job_name_regex, files)

        for matcher in matchers:
            # find the project-specific section
            for skipper in matcher.get('skip-if', []):
                if skipper.get('project'):
                    if re.search(skipper['project'], project['name']):
                        if 'all-files-match-any' in skipper:
                            applyIrrelevantFiles(
                                matcher['name'],
                                skipper['all-files-match-any'])

    def writeProject(self, project):
        '''
        Create a new v3 project definition.

        As part of creating the project, scan for project-specific job matchers
        referencing this project and remove the templates matching the job
        regex for that matcher. Expand the matched template(s) into the project
        so we can apply the project-specific matcher to the job(s).
        '''
        new_project = collections.OrderedDict()
        if 'name' in project:
            new_project['name'] = project['name']

        job_matchers = self.scanForProjectMatchers(project['name'])
        if job_matchers:
            exp_template_names = self.findReferencedTemplateNames(
                job_matchers, project['name'])
        else:
            exp_template_names = []

        templates_to_expand = []
        if 'template' in project:
            new_project['template'] = []
            for template in project['template']:
                if template['name'] in exp_template_names:
                    templates_to_expand.append(template['name'])
                    continue
                new_project['template'].append(dict(
                    name=self.mapping.getNewTemplateName(template['name'])))

        for key, value in project.items():
            if key in ('name', 'template'):
                continue
            else:
                new_project[key] = collections.OrderedDict()
                if key == 'gate':
                    for queue in self.change_queues:
                        if project['name'] not in queue.getProjects():
                            continue
                        if len(queue.getProjects()) == 1:
                            continue
                        new_project[key]['queue'] = queue.name
                tmp = [job for job in self.makeNewJobs(value)]
                self.job_objects.extend(tmp)
                jobs = [job.toPipelineDict() for job in tmp]
                new_project[key]['jobs'] = jobs

        for name in templates_to_expand:
            self.expandTemplateIntoProject(name, new_project)

        # Need a deep copy after expansion, else our templates end up
        # also getting this change.
        new_project = copy.deepcopy(new_project)
        self.applyProjectMatchers(job_matchers, new_project)

        return new_project

    def writeJobs(self):
        job_outfile, project_outfile = self.setupDir()
        job_config = []
        project_config = []

        for template in self.layout.get('project-templates', []):
            self.log.debug("Processing template: %s", template)
            new_template = self.writeProjectTemplate(template)
            self.new_templates[new_template['name']] = new_template
            if not self.mapping.hasProjectTemplate(template['name']):
                job_config.append({'project-template': new_template})

        project_names = []
        for project in self.layout.get('projects', []):
            project_names.append(project['name'])
            project_config.append(
                {'project': self.writeProject(project)})

        seen_jobs = []
        for job in sorted(self.job_objects, key=lambda job: job.name):
            if (job.name not in seen_jobs and
                    job.name not in self.mapping.seen_new_jobs and
                    job.emit):
                has_artifacts, has_post, has_draft = job.emitPlaybooks(
                    self.outdir, self.syntax_check)
                job_config.append({'job': job.toJobDict(
                    has_artifacts, has_post, has_draft, project_names)})
                seen_jobs.append(job.name)

        with open(job_outfile, 'w') as yamlout:
            # Insert an extra space between top-level list items
            yamlout.write(ordered_dump(job_config).replace('\n-', '\n\n-'))

        with open(project_outfile, 'w') as yamlout:
            # Insert an extra space between top-level list items
            yamlout.write(ordered_dump(project_config).replace('\n-', '\n\n-'))


def main():
    yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                         construct_yaml_map)

    yaml.add_representer(collections.OrderedDict, project_representer,
                         Dumper=IndentedDumper)
    yaml.representer.BaseRepresenter.represent_scalar = my_represent_scalar

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
        '--syntax-check', dest='syntax_check', action='store_true',
        help='Run ansible-playbook --syntax-check on generated playbooks')
    parser.add_argument(
        '-m', dest='move', action='store_true',
        help='Move zuul.yaml to zuul.d if it exists')

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    ZuulMigrate(args.layout, args.job_config, args.nodepool_config,
                args.outdir, args.mapping, args.move, args.syntax_check).run()


if __name__ == '__main__':
    main()
