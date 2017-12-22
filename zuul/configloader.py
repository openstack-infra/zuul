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

import base64
import collections
from contextlib import contextmanager
import copy
import os
import logging
import textwrap
import io
import re

import voluptuous as vs

from zuul import model
from zuul.lib import yamlutil as yaml
import zuul.manager.dependent
import zuul.manager.independent
from zuul import change_matcher
from zuul.lib import encryption


# Several forms accept either a single item or a list, this makes
# specifying that in the schema easy (and explicit).
def to_list(x):
    return vs.Any([x], x)


def as_list(item):
    if not item:
        return []
    if isinstance(item, list):
        return item
    return [item]


class ConfigurationSyntaxError(Exception):
    pass


class NodeFromGroupNotFoundError(Exception):
    def __init__(self, nodeset, node, group):
        message = textwrap.dedent("""\
        In nodeset "{nodeset}" the group "{group}" contains a
        node named "{node}" which is not defined in the nodeset.""")
        message = textwrap.fill(message.format(nodeset=nodeset,
                                               node=node, group=group))
        super(NodeFromGroupNotFoundError, self).__init__(message)


class DuplicateNodeError(Exception):
    def __init__(self, nodeset, node):
        message = textwrap.dedent("""\
        In nodeset "{nodeset}" the node "{node}" appears multiple times.
        Node names must be unique within a nodeset.""")
        message = textwrap.fill(message.format(nodeset=nodeset,
                                               node=node))
        super(DuplicateNodeError, self).__init__(message)


class MaxNodeError(Exception):
    def __init__(self, job, tenant):
        message = textwrap.dedent("""\
        The job "{job}" exceeds tenant max-nodes-per-job {maxnodes}.""")
        message = textwrap.fill(message.format(
            job=job.name, maxnodes=tenant.max_nodes_per_job))
        super(MaxNodeError, self).__init__(message)


class MaxTimeoutError(Exception):
    def __init__(self, job, tenant):
        message = textwrap.dedent("""\
        The job "{job}" exceeds tenant max-job-timeout {maxtimeout}.""")
        message = textwrap.fill(message.format(
            job=job.name, maxtimeout=tenant.max_job_timeout))
        super(MaxTimeoutError, self).__init__(message)


class DuplicateGroupError(Exception):
    def __init__(self, nodeset, group):
        message = textwrap.dedent("""\
        In nodeset "{nodeset}" the group "{group}" appears multiple times.
        Group names must be unique within a nodeset.""")
        message = textwrap.fill(message.format(nodeset=nodeset,
                                               group=group))
        super(DuplicateGroupError, self).__init__(message)


class ProjectNotFoundError(Exception):
    def __init__(self, project):
        message = textwrap.dedent("""\
        The project "{project}" was not found.  All projects
        referenced within a Zuul configuration must first be
        added to the main configuration file by the Zuul
        administrator.""")
        message = textwrap.fill(message.format(project=project))
        super(ProjectNotFoundError, self).__init__(message)


class TemplateNotFoundError(Exception):
    def __init__(self, template):
        message = textwrap.dedent("""\
        The project template "{template}" was not found.
        """)
        message = textwrap.fill(message.format(template=template))
        super(TemplateNotFoundError, self).__init__(message)


class SecretNotFoundError(Exception):
    def __init__(self, secret):
        message = textwrap.dedent("""\
        The secret "{secret}" was not found.
        """)
        message = textwrap.fill(message.format(secret=secret))
        super(SecretNotFoundError, self).__init__(message)


class NodesetNotFoundError(Exception):
    def __init__(self, nodeset):
        message = textwrap.dedent("""\
        The nodeset "{nodeset}" was not found.
        """)
        message = textwrap.fill(message.format(nodeset=nodeset))
        super(NodesetNotFoundError, self).__init__(message)


class PipelineNotPermittedError(Exception):
    def __init__(self):
        message = textwrap.dedent("""\
        Pipelines may not be defined in untrusted repos,
        they may only be defined in config repos.""")
        message = textwrap.fill(message)
        super(PipelineNotPermittedError, self).__init__(message)


class ProjectNotPermittedError(Exception):
    def __init__(self):
        message = textwrap.dedent("""\
        Within an untrusted project, the only project definition
        permitted is that of the project itself.""")
        message = textwrap.fill(message)
        super(ProjectNotPermittedError, self).__init__(message)


class YAMLDuplicateKeyError(ConfigurationSyntaxError):
    def __init__(self, key, node, context, start_mark):
        intro = textwrap.fill(textwrap.dedent("""\
        Zuul encountered a syntax error while parsing its configuration in the
        repo {repo} on branch {branch}.  The error was:""".format(
            repo=context.project.name,
            branch=context.branch,
        )))

        e = textwrap.fill(textwrap.dedent("""\
        The key "{key}" appears more than once; duplicate keys are not
        permitted.
        """.format(
            key=key,
        )))

        m = textwrap.dedent("""\
        {intro}

        {error}

        The error appears in the following stanza:

        {content}

        {start_mark}""")

        m = m.format(intro=intro,
                     error=indent(str(e)),
                     content=indent(start_mark.snippet.rstrip()),
                     start_mark=str(start_mark))
        super(YAMLDuplicateKeyError, self).__init__(m)


def indent(s):
    return '\n'.join(['  ' + x for x in s.split('\n')])


@contextmanager
def early_configuration_exceptions(context):
    try:
        yield
    except ConfigurationSyntaxError:
        raise
    except Exception as e:
        intro = textwrap.fill(textwrap.dedent("""\
        Zuul encountered a syntax error while parsing its configuration in the
        repo {repo} on branch {branch}.  The error was:""".format(
            repo=context.project.name,
            branch=context.branch,
        )))

        m = textwrap.dedent("""\
        {intro}

        {error}""")

        m = m.format(intro=intro,
                     error=indent(str(e)))
        raise ConfigurationSyntaxError(m)


@contextmanager
def configuration_exceptions(stanza, conf):
    try:
        yield
    except ConfigurationSyntaxError:
        raise
    except Exception as e:
        conf = copy.deepcopy(conf)
        context = conf.pop('_source_context')
        start_mark = conf.pop('_start_mark')
        intro = textwrap.fill(textwrap.dedent("""\
        Zuul encountered a syntax error while parsing its configuration in the
        repo {repo} on branch {branch}.  The error was:""".format(
            repo=context.project.name,
            branch=context.branch,
        )))

        m = textwrap.dedent("""\
        {intro}

        {error}

        The error appears in the following {stanza} stanza:

        {content}

        {start_mark}""")

        m = m.format(intro=intro,
                     error=indent(str(e)),
                     stanza=stanza,
                     content=indent(start_mark.snippet.rstrip()),
                     start_mark=str(start_mark))
        raise ConfigurationSyntaxError(m)


class ZuulMark(object):
    # The yaml mark class differs between the C and python versions.
    # The C version does not provide a snippet, and also appears to
    # lose data under some circumstances.
    def __init__(self, start_mark, end_mark, stream):
        self.name = start_mark.name
        self.index = start_mark.index
        self.line = start_mark.line
        self.column = start_mark.column
        self.snippet = stream[start_mark.index:end_mark.index]

    def __str__(self):
        return '  in "{name}", line {line}, column {column}'.format(
            name=self.name,
            line=self.line + 1,
            column=self.column + 1,
        )


class ZuulSafeLoader(yaml.SafeLoader):
    zuul_node_types = frozenset(('job', 'nodeset', 'secret', 'pipeline',
                                 'project', 'project-template',
                                 'semaphore', 'pragma'))

    def __init__(self, stream, context):
        wrapped_stream = io.StringIO(stream)
        wrapped_stream.name = str(context)
        super(ZuulSafeLoader, self).__init__(wrapped_stream)
        self.name = str(context)
        self.zuul_context = context
        self.zuul_stream = stream

    def construct_mapping(self, node, deep=False):
        keys = set()
        for k, v in node.value:
            if k.value in keys:
                mark = ZuulMark(node.start_mark, node.end_mark,
                                self.zuul_stream)
                raise YAMLDuplicateKeyError(k.value, node, self.zuul_context,
                                            mark)
            keys.add(k.value)
        r = super(ZuulSafeLoader, self).construct_mapping(node, deep)
        keys = frozenset(r.keys())
        if len(keys) == 1 and keys.intersection(self.zuul_node_types):
            d = list(r.values())[0]
            if isinstance(d, dict):
                d['_start_mark'] = ZuulMark(node.start_mark, node.end_mark,
                                            self.zuul_stream)
                d['_source_context'] = self.zuul_context
        return r


def safe_load_yaml(stream, context):
    loader = ZuulSafeLoader(stream, context)
    try:
        return loader.get_single_data()
    except yaml.YAMLError as e:
        m = """
Zuul encountered a syntax error while parsing its configuration in the
repo {repo} on branch {branch}.  The error was:

  {error}
"""
        m = m.format(repo=context.project.name,
                     branch=context.branch,
                     error=str(e))
        raise ConfigurationSyntaxError(m)
    finally:
        loader.dispose()


class EncryptedPKCS1_OAEP(yaml.YAMLObject):
    yaml_tag = u'!encrypted/pkcs1-oaep'
    yaml_loader = yaml.SafeLoader

    def __init__(self, ciphertext):
        if isinstance(ciphertext, list):
            self.ciphertext = [base64.b64decode(x.value)
                               for x in ciphertext]
        else:
            self.ciphertext = base64.b64decode(ciphertext)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, EncryptedPKCS1_OAEP):
            return False
        return (self.ciphertext == other.ciphertext)

    @classmethod
    def from_yaml(cls, loader, node):
        return cls(node.value)

    def decrypt(self, private_key):
        if isinstance(self.ciphertext, list):
            return ''.join([
                encryption.decrypt_pkcs1_oaep(chunk, private_key).
                decode('utf8')
                for chunk in self.ciphertext])
        else:
            return encryption.decrypt_pkcs1_oaep(self.ciphertext,
                                                 private_key).decode('utf8')


class PragmaParser(object):
    pragma = {
        'implied-branch-matchers': bool,
        'implied-branches': to_list(str),
        '_source_context': model.SourceContext,
        '_start_mark': ZuulMark,
    }

    schema = vs.Schema(pragma)

    def __init__(self):
        self.log = logging.getLogger("zuul.PragmaParser")

    def fromYaml(self, conf):
        with configuration_exceptions('project-template', conf):
            self.schema(conf)

        bm = conf.get('implied-branch-matchers')

        source_context = conf['_source_context']
        if bm is not None:
            source_context.implied_branch_matchers = bm

        branches = conf.get('implied-branches')
        if branches is not None:
            source_context.implied_branches = as_list(branches)


class NodeSetParser(object):
    @staticmethod
    def getSchema(anonymous=False):
        node = {vs.Required('name'): to_list(str),
                vs.Required('label'): str,
                }

        group = {vs.Required('name'): str,
                 vs.Required('nodes'): to_list(str),
                 }

        nodeset = {vs.Required('nodes'): to_list(node),
                   'groups': to_list(group),
                   '_source_context': model.SourceContext,
                   '_start_mark': ZuulMark,
                   }

        if not anonymous:
            nodeset[vs.Required('name')] = str
        return vs.Schema(nodeset)

    @staticmethod
    def fromYaml(conf, anonymous=False):
        NodeSetParser.getSchema(anonymous)(conf)
        ns = model.NodeSet(conf.get('name'))
        node_names = set()
        group_names = set()
        for conf_node in as_list(conf['nodes']):
            for name in as_list(conf_node['name']):
                if name in node_names:
                    raise DuplicateNodeError(name, conf_node['name'])
            node = model.Node(as_list(conf_node['name']), conf_node['label'])
            ns.addNode(node)
            for name in as_list(conf_node['name']):
                node_names.add(name)
        for conf_group in as_list(conf.get('groups', [])):
            for node_name in as_list(conf_group['nodes']):
                if node_name not in node_names:
                    raise NodeFromGroupNotFoundError(conf['name'], node_name,
                                                     conf_group['name'])
            if conf_group['name'] in group_names:
                raise DuplicateGroupError(conf['name'], conf_group['name'])
            group = model.Group(conf_group['name'], conf_group['nodes'])
            ns.addGroup(group)
            group_names.add(conf_group['name'])
        return ns


class SecretParser(object):
    @staticmethod
    def getSchema():
        data = {str: vs.Any(str, EncryptedPKCS1_OAEP)}

        secret = {vs.Required('name'): str,
                  vs.Required('data'): data,
                  '_source_context': model.SourceContext,
                  '_start_mark': ZuulMark,
                  }

        return vs.Schema(secret)

    @staticmethod
    def fromYaml(layout, conf):
        with configuration_exceptions('secret', conf):
            SecretParser.getSchema()(conf)
        s = model.Secret(conf['name'], conf['_source_context'])
        s.secret_data = conf['data']
        return s


class JobParser(object):
    ANSIBLE_ROLE_RE = re.compile(r'^(ansible[-_.+]*)*(role[-_.+]*)*')

    zuul_role = {vs.Required('zuul'): str,
                 'name': str}

    galaxy_role = {vs.Required('galaxy'): str,
                   'name': str}

    role = vs.Any(zuul_role, galaxy_role)

    job_project = {vs.Required('name'): str,
                   'override-branch': str,
                   'override-checkout': str}

    secret = {vs.Required('name'): str,
              vs.Required('secret'): str}

    # Attributes of a job that can also be used in Project and ProjectTemplate
    job_attributes = {'parent': vs.Any(str, None),
                      'final': bool,
                      'failure-message': str,
                      'success-message': str,
                      'failure-url': str,
                      'success-url': str,
                      'hold-following-changes': bool,
                      'voting': bool,
                      'semaphore': str,
                      'tags': to_list(str),
                      'branches': to_list(str),
                      'files': to_list(str),
                      'secrets': to_list(vs.Any(secret, str)),
                      'irrelevant-files': to_list(str),
                      # validation happens in NodeSetParser
                      'nodeset': vs.Any(dict, str),
                      'timeout': int,
                      'attempts': int,
                      'pre-run': to_list(str),
                      'post-run': to_list(str),
                      'run': str,
                      '_source_context': model.SourceContext,
                      '_start_mark': ZuulMark,
                      'roles': to_list(role),
                      'required-projects': to_list(vs.Any(job_project, str)),
                      'vars': dict,
                      'dependencies': to_list(str),
                      'allowed-projects': to_list(str),
                      'override-branch': str,
                      'override-checkout': str,
                      'description': str,
                      'post-review': bool}

    job_name = {vs.Required('name'): str}

    job = dict(collections.ChainMap(job_name, job_attributes))

    schema = vs.Schema(job)

    simple_attributes = [
        'final',
        'timeout',
        'workspace',
        'voting',
        'hold-following-changes',
        'semaphore',
        'attempts',
        'failure-message',
        'success-message',
        'failure-url',
        'success-url',
        'override-branch',
        'override-checkout',
    ]

    @staticmethod
    def _getImpliedBranches(tenant, job):
        # If the user has set a pragma directive for this, use the
        # value (if unset, the value is None).
        if job.source_context.implied_branch_matchers is True:
            if job.source_context.implied_branches is not None:
                return job.source_context.implied_branches
            return [job.source_context.branch]
        elif job.source_context.implied_branch_matchers is False:
            return None

        # If this is a trusted project, don't create implied branch
        # matchers.
        if job.source_context.trusted:
            return None

        # If this project only has one branch, don't create implied
        # branch matchers.  This way central job repos can work.
        branches = tenant.getProjectBranches(job.source_context.project)
        if len(branches) == 1:
            return None

        if job.source_context.implied_branches is not None:
            return job.source_context.implied_branches
        return [job.source_context.branch]

    @staticmethod
    def fromYaml(tenant, layout, conf, project_pipeline=False,
                 name=None, validate=True):
        if validate:
            with configuration_exceptions('job', conf):
                JobParser.schema(conf)

        if name is None:
            name = conf['name']

        # NB: The default detection system in the Job class requires
        # that we always assign values directly rather than modifying
        # them (e.g., "job.run = ..." rather than
        # "job.run.append(...)").

        job = model.Job(name)
        job.description = conf.get('description')
        job.source_context = conf.get('_source_context')
        job.source_line = conf.get('_start_mark').line + 1

        if 'parent' in conf:
            if conf['parent'] is not None:
                # Parent job is explicitly specified, so inherit from it.
                job.parent = conf['parent']
            else:
                # Parent is explicitly set as None, so user intends
                # this to be a base job.  That's only okay if we're in
                # a config project.
                if not conf['_source_context'].trusted:
                    raise Exception(
                        "Base jobs must be defined in config projects")
                job.parent = job.BASE_JOB_MARKER

        # Secrets are part of the playbook context so we must establish
        # them earlier than playbooks.
        secrets = []
        for secret_config in as_list(conf.get('secrets', [])):
            if isinstance(secret_config, str):
                secret_name = secret_config
                secret = layout.secrets.get(secret_name)
            else:
                secret_name = secret_config['name']
                secret = layout.secrets.get(secret_config['secret'])
            if secret is None:
                raise SecretNotFoundError(secret_name)
            if secret_name == 'zuul':
                raise Exception("Secrets named 'zuul' are not allowed.")
            if not secret.source_context.isSameProject(job.source_context):
                raise Exception(
                    "Unable to use secret %s.  Secrets must be "
                    "defined in the same project in which they "
                    "are used" % secret_name)
            # If the secret declares a different name, set it on the decrypted
            # copy of the secret object
            decrypted_secret = secret.decrypt(
                job.source_context.project.private_key)
            decrypted_secret.name = secret_name
            secrets.append(decrypted_secret)

        # A job in an untrusted repo that uses secrets requires
        # special care.  We must note this, and carry this flag
        # through inheritance to ensure that we don't run this job in
        # an unsafe check pipeline.
        if secrets and not conf['_source_context'].trusted:
            job.post_review = True

        if conf.get('timeout') and tenant.max_job_timeout != -1 and \
           int(conf['timeout']) > tenant.max_job_timeout:
            raise MaxTimeoutError(job, tenant)

        if 'post-review' in conf:
            if conf['post-review']:
                job.post_review = True
            else:
                raise Exception("Once set, the post-review attribute "
                                "may not be unset")

        # Roles are part of the playbook context so we must establish
        # them earlier than playbooks.
        roles = []
        if 'roles' in conf:
            for role in conf.get('roles', []):
                if 'zuul' in role:
                    r = JobParser._makeZuulRole(tenant, job, role)
                    if r:
                        roles.append(r)
        # A job's repo should be an implicit role source for that job,
        # but not in a project-pipeline variant.
        if not project_pipeline:
            r = JobParser._makeImplicitRole(job)
            roles.insert(0, r)
        job.addRoles(roles)

        for pre_run_name in as_list(conf.get('pre-run')):
            pre_run = model.PlaybookContext(job.source_context,
                                            pre_run_name, job.roles,
                                            secrets)
            job.pre_run = job.pre_run + (pre_run,)
        # NOTE(pabelanger): Reverse the order of our post-run list. We prepend
        # post-runs for inherits however, we want to execute post-runs in the
        # order they are listed within the job.
        for post_run_name in reversed(as_list(conf.get('post-run'))):
            post_run = model.PlaybookContext(job.source_context,
                                             post_run_name, job.roles,
                                             secrets)
            job.post_run = (post_run,) + job.post_run
        if 'run' in conf:
            run = model.PlaybookContext(job.source_context, conf['run'],
                                        job.roles, secrets)
            job.run = (run,)

        for k in JobParser.simple_attributes:
            a = k.replace('-', '_')
            if k in conf:
                setattr(job, a, conf[k])
        if 'nodeset' in conf:
            conf_nodeset = conf['nodeset']
            if isinstance(conf_nodeset, str):
                # This references an existing named nodeset in the layout.
                ns = layout.nodesets.get(conf_nodeset)
                if ns is None:
                    raise NodesetNotFoundError(conf_nodeset)
            else:
                ns = NodeSetParser.fromYaml(conf_nodeset, anonymous=True)
            if tenant.max_nodes_per_job != -1 and \
               len(ns) > tenant.max_nodes_per_job:
                raise MaxNodeError(job, tenant)
            job.nodeset = ns

        if 'required-projects' in conf:
            new_projects = {}
            projects = as_list(conf.get('required-projects', []))
            for project in projects:
                if isinstance(project, dict):
                    project_name = project['name']
                    project_override_branch = project.get('override-branch')
                    project_override_checkout = project.get(
                        'override-checkout')
                else:
                    project_name = project
                    project_override_branch = None
                    project_override_checkout = None
                (trusted, project) = tenant.getProject(project_name)
                if project is None:
                    raise Exception("Unknown project %s" % (project_name,))
                job_project = model.JobProject(project_name,
                                               project_override_branch,
                                               project_override_checkout)
                new_projects[project_name] = job_project
            job.required_projects = new_projects

        tags = conf.get('tags')
        if tags:
            job.tags = set(tags)

        job.dependencies = frozenset(as_list(conf.get('dependencies')))

        variables = conf.get('vars', None)
        if variables:
            if 'zuul' in variables:
                raise Exception("Variables named 'zuul' are not allowed.")
            job.variables = variables

        allowed_projects = conf.get('allowed-projects', None)
        if allowed_projects:
            allowed = []
            for p in as_list(allowed_projects):
                (trusted, project) = tenant.getProject(p)
                if project is None:
                    raise Exception("Unknown project %s" % (p,))
                allowed.append(project.name)
            job.allowed_projects = frozenset(allowed)

        branches = None
        if ('branches' not in conf):
            branches = JobParser._getImpliedBranches(tenant, job)
        if (not branches) and ('branches' in conf):
            branches = as_list(conf['branches'])
        if branches:
            job.setBranchMatcher(branches)
        if 'files' in conf:
            matchers = []
            for fn in as_list(conf['files']):
                matchers.append(change_matcher.FileMatcher(fn))
            job.file_matcher = change_matcher.MatchAny(matchers)
        if 'irrelevant-files' in conf:
            matchers = []
            for fn in as_list(conf['irrelevant-files']):
                matchers.append(change_matcher.FileMatcher(fn))
            job.irrelevant_file_matcher = change_matcher.MatchAllFiles(
                matchers)
        return job

    @staticmethod
    def _makeZuulRole(tenant, job, role):
        name = role['zuul'].split('/')[-1]

        (trusted, project) = tenant.getProject(role['zuul'])
        if project is None:
            return None

        return model.ZuulRole(role.get('name', name),
                              project.connection_name,
                              project.name)

    @staticmethod
    def _makeImplicitRole(job):
        project = job.source_context.project
        name = project.name.split('/')[-1]
        name = JobParser.ANSIBLE_ROLE_RE.sub('', name)
        return model.ZuulRole(name,
                              project.connection_name,
                              project.name,
                              implicit=True)


class ProjectTemplateParser(object):
    def __init__(self, tenant, layout):
        self.log = logging.getLogger("zuul.ProjectTemplateParser")
        self.tenant = tenant
        self.layout = layout
        self.schema = self.getSchema()

    def getSchema(self):
        project_template = {
            vs.Required('name'): str,
            'description': str,
            'merge-mode': vs.Any(
                'merge', 'merge-resolve',
                'cherry-pick'),
            '_source_context': model.SourceContext,
            '_start_mark': ZuulMark,
        }

        job = {str: vs.Any(str, JobParser.job_attributes)}
        job_list = [vs.Any(str, job)]
        pipeline_contents = {
            'queue': str,
            'debug': bool,
            'jobs': job_list,
        }

        for p in self.layout.pipelines.values():
            project_template[p.name] = pipeline_contents
        return vs.Schema(project_template)

    def fromYaml(self, conf, validate=True):
        if validate:
            with configuration_exceptions('project-template', conf):
                self.schema(conf)
        source_context = conf['_source_context']
        project_template = model.ProjectConfig(conf['name'], source_context)
        start_mark = conf['_start_mark']
        for pipeline in self.layout.pipelines.values():
            conf_pipeline = conf.get(pipeline.name)
            if not conf_pipeline:
                continue
            project_pipeline = model.ProjectPipelineConfig()
            project_template.pipelines[pipeline.name] = project_pipeline
            project_pipeline.queue_name = conf_pipeline.get('queue')
            project_pipeline.debug = conf_pipeline.get('debug')
            self.parseJobList(
                conf_pipeline.get('jobs', []),
                source_context, start_mark, project_pipeline.job_list)
        return project_template

    def parseJobList(self, conf, source_context, start_mark, job_list):
        for conf_job in conf:
            if isinstance(conf_job, str):
                jobname = conf_job
                attrs = {}
            elif isinstance(conf_job, dict):
                # A dictionary in a job tree may override params
                jobname, attrs = list(conf_job.items())[0]
            else:
                raise Exception("Job must be a string or dictionary")
            attrs['_source_context'] = source_context
            attrs['_start_mark'] = start_mark

            # validate that the job is existing
            with configuration_exceptions('project or project-template',
                                          attrs):
                self.layout.getJob(jobname)

            job_list.addJob(JobParser.fromYaml(self.tenant, self.layout,
                                               attrs, project_pipeline=True,
                                               name=jobname, validate=False))


class ProjectParser(object):
    def __init__(self, tenant, layout, project_template_parser):
        self.log = logging.getLogger("zuul.ProjectParser")
        self.tenant = tenant
        self.layout = layout
        self.project_template_parser = project_template_parser
        self.schema = self.getSchema()

    def getSchema(self):
        project = {
            'name': str,
            'description': str,
            'templates': [str],
            'merge-mode': vs.Any('merge', 'merge-resolve',
                                 'cherry-pick'),
            'default-branch': str,
            '_source_context': model.SourceContext,
            '_start_mark': ZuulMark,
        }

        job = {str: vs.Any(str, JobParser.job_attributes)}
        job_list = [vs.Any(str, job)]
        pipeline_contents = {
            'queue': str,
            'debug': bool,
            'jobs': job_list
        }

        for p in self.layout.pipelines.values():
            project[p.name] = pipeline_contents
        return vs.Schema(project)

    def fromYaml(self, conf_list):
        for conf in conf_list:
            with configuration_exceptions('project', conf):
                self.schema(conf)

        with configuration_exceptions('project', conf_list[0]):
            project_name = conf_list[0]['name']
            (trusted, project) = self.tenant.getProject(project_name)
            if project is None:
                raise ProjectNotFoundError(project_name)
            project_config = model.ProjectConfig(project.canonical_name)

        configs = []
        for conf in conf_list:
            implied_branch = None
            with configuration_exceptions('project', conf):
                if not conf['_source_context'].trusted:
                    if project != conf['_source_context'].project:
                        raise ProjectNotPermittedError()

                conf_templates = conf.get('templates', [])
                # The way we construct a project definition is by
                # parsing the definition as a template, then applying
                # all of the templates, including the newly parsed
                # one, in order.
                project_template = self.project_template_parser.fromYaml(
                    conf, validate=False)
                # If this project definition is in a place where it
                # should get implied branch matchers, set it.
                if (not conf['_source_context'].trusted):
                    implied_branch = conf['_source_context'].branch
                for name in conf_templates:
                    if name not in self.layout.project_templates:
                        raise TemplateNotFoundError(name)
                configs.extend([(self.layout.project_templates[name],
                                 implied_branch)
                                for name in conf_templates])
                configs.append((project_template, implied_branch))
                # Set the following values to the first one that we
                # find and ignore subsequent settings.
                mode = conf.get('merge-mode')
                if mode and project_config.merge_mode is None:
                    project_config.merge_mode = model.MERGER_MAP[mode]
                default_branch = conf.get('default-branch')
                if default_branch and project_config.default_branch is None:
                    project_config.default_branch = default_branch
        if project_config.merge_mode is None:
            # If merge mode was not specified in any project stanza,
            # set it to the default.
            project_config.merge_mode = model.MERGER_MAP['merge-resolve']
        if project_config.default_branch is None:
            project_config.default_branch = 'master'
        for pipeline in self.layout.pipelines.values():
            project_pipeline = model.ProjectPipelineConfig()
            queue_name = None
            debug = False
            # For every template, iterate over the job tree and replace or
            # create the jobs in the final definition as needed.
            pipeline_defined = False
            for (template, implied_branch) in configs:
                if pipeline.name in template.pipelines:
                    pipeline_defined = True
                    template_pipeline = template.pipelines[pipeline.name]
                    project_pipeline.job_list.inheritFrom(
                        template_pipeline.job_list,
                        implied_branch)
                    if template_pipeline.queue_name:
                        queue_name = template_pipeline.queue_name
                    if template_pipeline.debug is not None:
                        debug = template_pipeline.debug
            if queue_name:
                project_pipeline.queue_name = queue_name
            if debug:
                project_pipeline.debug = True
            if pipeline_defined:
                project_config.pipelines[pipeline.name] = project_pipeline
        return project_config


class PipelineParser(object):
    log = logging.getLogger("zuul.PipelineParser")

    # A set of reporter configuration keys to action mapping
    reporter_actions = {
        'start': 'start_actions',
        'success': 'success_actions',
        'failure': 'failure_actions',
        'merge-failure': 'merge_failure_actions',
        'disabled': 'disabled_actions',
    }

    @staticmethod
    def getDriverSchema(dtype, connections):
        methods = {
            'trigger': 'getTriggerSchema',
            'reporter': 'getReporterSchema',
            'require': 'getRequireSchema',
            'reject': 'getRejectSchema',
        }

        schema = {}
        # Add the configured connections as available layout options
        for connection_name, connection in connections.connections.items():
            method = getattr(connection.driver, methods[dtype], None)
            if method:
                schema[connection_name] = to_list(method())

        return schema

    @staticmethod
    def getSchema(layout, connections):
        manager = vs.Any('independent',
                         'dependent')

        precedence = vs.Any('normal', 'low', 'high')

        window = vs.All(int, vs.Range(min=0))
        window_floor = vs.All(int, vs.Range(min=1))
        window_type = vs.Any('linear', 'exponential')
        window_factor = vs.All(int, vs.Range(min=1))

        pipeline = {vs.Required('name'): str,
                    vs.Required('manager'): manager,
                    'precedence': precedence,
                    'description': str,
                    'success-message': str,
                    'failure-message': str,
                    'merge-failure-message': str,
                    'footer-message': str,
                    'dequeue-on-new-patchset': bool,
                    'ignore-dependencies': bool,
                    'post-review': bool,
                    'disable-after-consecutive-failures':
                        vs.All(int, vs.Range(min=1)),
                    'window': window,
                    'window-floor': window_floor,
                    'window-increase-type': window_type,
                    'window-increase-factor': window_factor,
                    'window-decrease-type': window_type,
                    'window-decrease-factor': window_factor,
                    '_source_context': model.SourceContext,
                    '_start_mark': ZuulMark,
                    }
        pipeline['require'] = PipelineParser.getDriverSchema('require',
                                                             connections)
        pipeline['reject'] = PipelineParser.getDriverSchema('reject',
                                                            connections)
        pipeline['trigger'] = vs.Required(
            PipelineParser.getDriverSchema('trigger', connections))
        for action in ['start', 'success', 'failure', 'merge-failure',
                       'disabled']:
            pipeline[action] = PipelineParser.getDriverSchema('reporter',
                                                              connections)
        return vs.Schema(pipeline)

    @staticmethod
    def fromYaml(layout, connections, scheduler, conf):
        with configuration_exceptions('pipeline', conf):
            PipelineParser.getSchema(layout, connections)(conf)
        pipeline = model.Pipeline(conf['name'], layout)
        pipeline.description = conf.get('description')

        precedence = model.PRECEDENCE_MAP[conf.get('precedence')]
        pipeline.precedence = precedence
        pipeline.failure_message = conf.get('failure-message',
                                            "Build failed.")
        pipeline.merge_failure_message = conf.get(
            'merge-failure-message', "Merge Failed.\n\nThis change or one "
            "of its cross-repo dependencies was unable to be "
            "automatically merged with the current state of its "
            "repository. Please rebase the change and upload a new "
            "patchset.")
        pipeline.success_message = conf.get('success-message',
                                            "Build succeeded.")
        pipeline.footer_message = conf.get('footer-message', "")
        pipeline.start_message = conf.get('start-message',
                                          "Starting {pipeline.name} jobs.")
        pipeline.dequeue_on_new_patchset = conf.get(
            'dequeue-on-new-patchset', True)
        pipeline.ignore_dependencies = conf.get(
            'ignore-dependencies', False)
        pipeline.post_review = conf.get(
            'post-review', False)

        for conf_key, action in PipelineParser.reporter_actions.items():
            reporter_set = []
            if conf.get(conf_key):
                for reporter_name, params \
                    in conf.get(conf_key).items():
                    reporter = connections.getReporter(reporter_name,
                                                       params)
                    reporter.setAction(conf_key)
                    reporter_set.append(reporter)
            setattr(pipeline, action, reporter_set)

        # If merge-failure actions aren't explicit, use the failure actions
        if not pipeline.merge_failure_actions:
            pipeline.merge_failure_actions = pipeline.failure_actions

        pipeline.disable_at = conf.get(
            'disable-after-consecutive-failures', None)

        pipeline.window = conf.get('window', 20)
        pipeline.window_floor = conf.get('window-floor', 3)
        pipeline.window_increase_type = conf.get(
            'window-increase-type', 'linear')
        pipeline.window_increase_factor = conf.get(
            'window-increase-factor', 1)
        pipeline.window_decrease_type = conf.get(
            'window-decrease-type', 'exponential')
        pipeline.window_decrease_factor = conf.get(
            'window-decrease-factor', 2)

        manager_name = conf['manager']
        if manager_name == 'dependent':
            manager = zuul.manager.dependent.DependentPipelineManager(
                scheduler, pipeline)
        elif manager_name == 'independent':
            manager = zuul.manager.independent.IndependentPipelineManager(
                scheduler, pipeline)

        pipeline.setManager(manager)
        layout.pipelines[conf['name']] = pipeline

        for source_name, require_config in conf.get('require', {}).items():
            source = connections.getSource(source_name)
            manager.ref_filters.extend(
                source.getRequireFilters(require_config))

        for source_name, reject_config in conf.get('reject', {}).items():
            source = connections.getSource(source_name)
            manager.ref_filters.extend(
                source.getRejectFilters(reject_config))

        for trigger_name, trigger_config in conf.get('trigger').items():
            trigger = connections.getTrigger(trigger_name, trigger_config)
            pipeline.triggers.append(trigger)
            manager.event_filters.extend(
                trigger.getEventFilters(conf['trigger'][trigger_name]))

        return pipeline


class SemaphoreParser(object):
    @staticmethod
    def getSchema():
        semaphore = {vs.Required('name'): str,
                     'max': int,
                     '_source_context': model.SourceContext,
                     '_start_mark': ZuulMark,
                     }

        return vs.Schema(semaphore)

    @staticmethod
    def fromYaml(conf):
        SemaphoreParser.getSchema()(conf)
        semaphore = model.Semaphore(conf['name'], conf.get('max', 1))
        semaphore.source_context = conf.get('_source_context')
        return semaphore


class TenantParser(object):
    log = logging.getLogger("zuul.TenantParser")

    classes = vs.Any('pipeline', 'job', 'semaphore', 'project',
                     'project-template', 'nodeset', 'secret')

    project_dict = {str: {
        'include': to_list(classes),
        'exclude': to_list(classes),
        'shadow': to_list(str),
        'exclude-unprotected-branches': bool,
    }}

    project = vs.Any(str, project_dict)

    group = {
        'include': to_list(classes),
        'exclude': to_list(classes),
        vs.Required('projects'): to_list(project),
    }

    project_or_group = vs.Any(project, group)

    tenant_source = vs.Schema({
        'config-projects': to_list(project_or_group),
        'untrusted-projects': to_list(project_or_group),
    })

    @staticmethod
    def validateTenantSources(connections):
        def v(value, path=[]):
            if isinstance(value, dict):
                for k, val in value.items():
                    connections.getSource(k)
                    TenantParser.validateTenantSource(val, path + [k])
            else:
                raise vs.Invalid("Invalid tenant source", path)
        return v

    @staticmethod
    def validateTenantSource(value, path=[]):
        TenantParser.tenant_source(value)

    @staticmethod
    def getSchema(connections=None):
        tenant = {vs.Required('name'): str,
                  'max-nodes-per-job': int,
                  'max-job-timeout': int,
                  'source': TenantParser.validateTenantSources(connections),
                  'exclude-unprotected-branches': bool,
                  'default-parent': str,
                  }
        return vs.Schema(tenant)

    @staticmethod
    def fromYaml(base, project_key_dir, connections, scheduler, merger, conf,
                 old_tenant):
        TenantParser.getSchema(connections)(conf)
        tenant = model.Tenant(conf['name'])
        if conf.get('max-nodes-per-job') is not None:
            tenant.max_nodes_per_job = conf['max-nodes-per-job']
        if conf.get('max-job-timeout') is not None:
            tenant.max_job_timeout = int(conf['max-job-timeout'])
        if conf.get('exclude-unprotected-branches') is not None:
            tenant.exclude_unprotected_branches = \
                conf['exclude-unprotected-branches']
        tenant.default_base_job = conf.get('default-parent', 'base')

        tenant.unparsed_config = conf
        unparsed_config = model.UnparsedTenantConfig()
        # tpcs is TenantProjectConfigs
        config_tpcs, untrusted_tpcs = \
            TenantParser._loadTenantProjects(
                project_key_dir, connections, conf)
        for tpc in config_tpcs:
            tenant.addConfigProject(tpc)
        for tpc in untrusted_tpcs:
            tenant.addUntrustedProject(tpc)

        for tpc in config_tpcs + untrusted_tpcs:
            TenantParser._getProjectBranches(tenant, tpc, old_tenant)
            TenantParser._resolveShadowProjects(tenant, tpc)

        if old_tenant:
            cached = True
        else:
            cached = False
        tenant.config_projects_config, tenant.untrusted_projects_config = \
            TenantParser._loadTenantInRepoLayouts(merger, connections,
                                                  tenant.config_projects,
                                                  tenant.untrusted_projects,
                                                  cached, tenant)
        unparsed_config.extend(tenant.config_projects_config, tenant=tenant)
        unparsed_config.extend(tenant.untrusted_projects_config, tenant=tenant)
        tenant.layout = TenantParser._parseLayout(base, tenant,
                                                  unparsed_config,
                                                  scheduler,
                                                  connections)
        return tenant

    @staticmethod
    def _resolveShadowProjects(tenant, tpc):
        shadow_projects = []
        for sp in tpc.shadow_projects:
            shadow_projects.append(tenant.getProject(sp)[1])
        tpc.shadow_projects = frozenset(shadow_projects)

    @staticmethod
    def _getProjectBranches(tenant, tpc, old_tenant):
        # If we're performing a tenant reconfiguration, we will have
        # an old_tenant object, however, we may be doing so because of
        # a branch creation event, so if we don't have any cached
        # data, query the branches again as well.
        if old_tenant and tpc.project.unparsed_config:
            branches = old_tenant.getProjectBranches(tpc.project)[:]
        else:
            branches = sorted(tpc.project.source.getProjectBranches(
                tpc.project, tenant))
        if 'master' in branches:
            branches.remove('master')
            branches = ['master'] + branches
        tpc.branches = branches

    @staticmethod
    def _loadProjectKeys(project_key_dir, connection_name, project):
        project.private_key_file = (
            os.path.join(project_key_dir, connection_name,
                         project.name + '.pem'))

        TenantParser._generateKeys(project)
        TenantParser._loadKeys(project)

    @staticmethod
    def _generateKeys(project):
        if os.path.isfile(project.private_key_file):
            return

        key_dir = os.path.dirname(project.private_key_file)
        if not os.path.isdir(key_dir):
            os.makedirs(key_dir, 0o700)

        TenantParser.log.info(
            "Generating RSA keypair for project %s" % (project.name,)
        )
        private_key, public_key = encryption.generate_rsa_keypair()
        pem_private_key = encryption.serialize_rsa_private_key(private_key)

        # Dump keys to filesystem.  We only save the private key
        # because the public key can be constructed from it.
        TenantParser.log.info(
            "Saving RSA keypair for project %s to %s" % (
                project.name, project.private_key_file)
        )
        with open(project.private_key_file, 'wb') as f:
            f.write(pem_private_key)

        # Ensure private key is read/write for zuul user only.
        os.chmod(project.private_key_file, 0o600)

    @staticmethod
    def _loadKeys(project):
        # Check the key files specified are there
        if not os.path.isfile(project.private_key_file):
            raise Exception(
                'Private key file {0} not found'.format(
                    project.private_key_file))

        # Load keypair
        with open(project.private_key_file, "rb") as f:
            (project.private_key, project.public_key) = \
                encryption.deserialize_rsa_keypair(f.read())

    @staticmethod
    def _getProject(source, conf, current_include):
        if isinstance(conf, str):
            # Return a project object whether conf is a dict or a str
            project = source.getProject(conf)
            project_include = current_include
            shadow_projects = []
            project_exclude_unprotected_branches = None
        else:
            project_name = list(conf.keys())[0]
            project = source.getProject(project_name)
            shadow_projects = as_list(conf[project_name].get('shadow', []))

            project_include = frozenset(
                as_list(conf[project_name].get('include', [])))
            if not project_include:
                project_include = current_include
            project_exclude = frozenset(
                as_list(conf[project_name].get('exclude', [])))
            if project_exclude:
                project_include = frozenset(project_include - project_exclude)
            project_exclude_unprotected_branches = conf[project_name].get(
                'exclude-unprotected-branches', None)

        tenant_project_config = model.TenantProjectConfig(project)
        tenant_project_config.load_classes = frozenset(project_include)
        tenant_project_config.shadow_projects = shadow_projects
        tenant_project_config.exclude_unprotected_branches = \
            project_exclude_unprotected_branches

        return tenant_project_config

    @staticmethod
    def _getProjects(source, conf, current_include):
        # Return a project object whether conf is a dict or a str
        projects = []
        if isinstance(conf, str):
            # A simple project name string
            projects.append(TenantParser._getProject(
                source, conf, current_include))
        elif len(conf.keys()) > 1 and 'projects' in conf:
            # This is a project group
            if 'include' in conf:
                current_include = set(as_list(conf['include']))
            else:
                current_include = current_include.copy()
            if 'exclude' in conf:
                exclude = set(as_list(conf['exclude']))
                current_include = current_include - exclude
            for project in conf['projects']:
                sub_projects = TenantParser._getProjects(
                    source, project, current_include)
                projects.extend(sub_projects)
        elif len(conf.keys()) == 1:
            # A project with overrides
            projects.append(TenantParser._getProject(
                source, conf, current_include))
        else:
            raise Exception("Unable to parse project %s", conf)
        return projects

    @staticmethod
    def _loadTenantProjects(project_key_dir, connections, conf_tenant):
        config_projects = []
        untrusted_projects = []

        default_include = frozenset(['pipeline', 'job', 'semaphore', 'project',
                                     'secret', 'project-template', 'nodeset'])

        for source_name, conf_source in conf_tenant.get('source', {}).items():
            source = connections.getSource(source_name)

            current_include = default_include
            for conf_repo in conf_source.get('config-projects', []):
                # tpcs = TenantProjectConfigs
                tpcs = TenantParser._getProjects(source, conf_repo,
                                                 current_include)
                for tpc in tpcs:
                    TenantParser._loadProjectKeys(
                        project_key_dir, source_name, tpc.project)
                    config_projects.append(tpc)

            current_include = frozenset(default_include - set(['pipeline']))
            for conf_repo in conf_source.get('untrusted-projects', []):
                tpcs = TenantParser._getProjects(source, conf_repo,
                                                 current_include)
                for tpc in tpcs:
                    TenantParser._loadProjectKeys(
                        project_key_dir, source_name, tpc.project)
                    untrusted_projects.append(tpc)

        return config_projects, untrusted_projects

    @staticmethod
    def _loadTenantInRepoLayouts(merger, connections, config_projects,
                                 untrusted_projects, cached, tenant):
        config_projects_config = model.UnparsedTenantConfig()
        untrusted_projects_config = model.UnparsedTenantConfig()
        # project -> config; these will replace
        # project.unparsed_config if this method succesfully
        # completes
        new_project_unparsed_config = {}
        # project -> branch -> config; these will replace
        # project.unparsed_branch_config if this method succesfully
        # completes
        new_project_unparsed_branch_config = {}
        jobs = []

        # In some cases, we can use cached data, but it's still
        # important that we process that in the same order along with
        # any jobs that we run.  This class is used to hold the cached
        # data and is inserted in the ordered jobs list for later
        # processing.
        class CachedDataJob(object):
            def __init__(self, config_project, project):
                self.config_project = config_project
                self.project = project

        for project in config_projects:
            # If we have cached data (this is a reconfiguration) use it.
            if cached and project.unparsed_config:
                jobs.append(CachedDataJob(True, project))
                continue
            # Otherwise, prepare an empty unparsed config object to
            # hold cached data later.
            new_project_unparsed_config[project] = model.UnparsedTenantConfig()
            # Get main config files.  These files are permitted the
            # full range of configuration.
            job = merger.getFiles(
                project.source.connection.connection_name,
                project.name, 'master',
                files=['zuul.yaml', '.zuul.yaml'],
                dirs=['zuul.d', '.zuul.d'])
            job.source_context = model.SourceContext(project, 'master',
                                                     '', True)
            jobs.append(job)

        for project in untrusted_projects:
            # If we have cached data (this is a reconfiguration) use it.
            if cached and project.unparsed_config:
                jobs.append(CachedDataJob(False, project))
                continue
            # Otherwise, prepare an empty unparsed config object to
            # hold cached data later.
            new_project_unparsed_config[project] = model.UnparsedTenantConfig()
            new_project_unparsed_branch_config[project] = {}
            # Get in-project-repo config files which have a restricted
            # set of options.
            # For each branch in the repo, get the zuul.yaml for that
            # branch.  Remember the branch and then implicitly add a
            # branch selector to each job there.  This makes the
            # in-repo configuration apply only to that branch.
            branches = tenant.getProjectBranches(project)
            for branch in branches:
                new_project_unparsed_branch_config[project][branch] = \
                    model.UnparsedTenantConfig()
                job = merger.getFiles(
                    project.source.connection.connection_name,
                    project.name, branch,
                    files=['zuul.yaml', '.zuul.yaml'],
                    dirs=['zuul.d', '.zuul.d'])
                job.source_context = model.SourceContext(
                    project, branch, '', False)
                jobs.append(job)

        for job in jobs:
            # Note: this is an ordered list -- we wait for cat jobs to
            # complete in the order they were executed which is the
            # same order they were defined in the main config file.
            # This is important for correct inheritance.
            if isinstance(job, CachedDataJob):
                TenantParser.log.info(
                    "Loading previously parsed configuration from %s" %
                    (job.project,))
                if job.config_project:
                    config_projects_config.extend(
                        job.project.unparsed_config)
                else:
                    untrusted_projects_config.extend(
                        job.project.unparsed_config)
                continue
            TenantParser.log.debug("Waiting for cat job %s" % (job,))
            job.wait()
            if not job.updated:
                raise Exception("Cat job %s failed" % (job,))
            TenantParser.log.debug("Cat job %s got files %s" %
                                   (job, job.files.keys()))
            loaded = False
            files = sorted(job.files.keys())
            for conf_root in ['zuul.yaml', 'zuul.d', '.zuul.yaml', '.zuul.d']:
                for fn in files:
                    fn_root = fn.split('/')[0]
                    if fn_root != conf_root or not job.files.get(fn):
                        continue
                    # Don't load from more than configuration in a repo-branch
                    if loaded and loaded != conf_root:
                        TenantParser.log.warning(
                            "Multiple configuration files in %s" %
                            (job.source_context,))
                        continue
                    loaded = conf_root
                    source_context = job.source_context.copy()
                    source_context.path = fn
                    TenantParser.log.info(
                        "Loading configuration from %s" %
                        (source_context,))
                    project = source_context.project
                    branch = source_context.branch
                    if source_context.trusted:
                        incdata = TenantParser._parseConfigProjectLayout(
                            job.files[fn], source_context)
                        config_projects_config.extend(incdata)
                    else:
                        incdata = TenantParser._parseUntrustedProjectLayout(
                            job.files[fn], source_context)
                        untrusted_projects_config.extend(incdata)
                    new_project_unparsed_config[project].extend(incdata)
                    if branch in new_project_unparsed_branch_config.get(
                            project, {}):
                        new_project_unparsed_branch_config[project][branch].\
                            extend(incdata)
        # Now that we've sucessfully loaded all of the configuration,
        # cache the unparsed data on the project objects.
        for project, data in new_project_unparsed_config.items():
            project.unparsed_config = data
        for project, branch_config in \
            new_project_unparsed_branch_config.items():
            for branch, data in branch_config.items():
                project.unparsed_branch_config[branch] = data
        return config_projects_config, untrusted_projects_config

    @staticmethod
    def _parseConfigProjectLayout(data, source_context):
        # This is the top-level configuration for a tenant.
        config = model.UnparsedTenantConfig()
        with early_configuration_exceptions(source_context):
            config.extend(safe_load_yaml(data, source_context))
        return config

    @staticmethod
    def _parseUntrustedProjectLayout(data, source_context):
        config = model.UnparsedTenantConfig()
        with early_configuration_exceptions(source_context):
            config.extend(safe_load_yaml(data, source_context))
        if config.pipelines:
            with configuration_exceptions('pipeline', config.pipelines[0]):
                raise PipelineNotPermittedError()
        return config

    @staticmethod
    def _getLoadClasses(tenant, conf_object):
        project = conf_object['_source_context'].project
        tpc = tenant.project_configs[project.canonical_name]
        return tpc.load_classes

    @staticmethod
    def _parseLayoutItems(layout, tenant, data, scheduler, connections,
                          skip_pipelines=False, skip_semaphores=False):
        # Handle pragma items first since they modify the source context
        # used by other classes.
        pragma_parser = PragmaParser()
        for config_pragma in data.pragmas:
            pragma_parser.fromYaml(config_pragma)

        if not skip_pipelines:
            for config_pipeline in data.pipelines:
                classes = TenantParser._getLoadClasses(
                    tenant, config_pipeline)
                if 'pipeline' not in classes:
                    continue
                layout.addPipeline(PipelineParser.fromYaml(
                    layout, connections,
                    scheduler, config_pipeline))

        for config_nodeset in data.nodesets:
            classes = TenantParser._getLoadClasses(tenant, config_nodeset)
            if 'nodeset' not in classes:
                continue
            with configuration_exceptions('nodeset', config_nodeset):
                layout.addNodeSet(NodeSetParser.fromYaml(
                    config_nodeset))

        for config_secret in data.secrets:
            classes = TenantParser._getLoadClasses(tenant, config_secret)
            if 'secret' not in classes:
                continue
            layout.addSecret(SecretParser.fromYaml(layout, config_secret))

        for config_job in data.jobs:
            classes = TenantParser._getLoadClasses(tenant, config_job)
            if 'job' not in classes:
                continue
            with configuration_exceptions('job', config_job):
                job = JobParser.fromYaml(tenant, layout, config_job)
                added = layout.addJob(job)
                if not added:
                    TenantParser.log.debug(
                        "Skipped adding job %s which shadows an existing job" %
                        (job,))

        # Now that all the jobs are loaded, verify their parents exist
        for config_job in data.jobs:
            classes = TenantParser._getLoadClasses(tenant, config_job)
            if 'job' not in classes:
                continue
            with configuration_exceptions('job', config_job):
                parent = config_job.get('parent')
                if parent:
                    layout.getJob(parent)

        if not skip_semaphores:
            for config_semaphore in data.semaphores:
                classes = TenantParser._getLoadClasses(
                    tenant, config_semaphore)
                if 'semaphore' not in classes:
                    continue
                semaphore = SemaphoreParser.fromYaml(config_semaphore)
                old_semaphore = layout.semaphores.get(semaphore.name)
                if (old_semaphore and
                    (old_semaphore.source_context.project ==
                     semaphore.source_context.project)):
                    # If a semaphore shows up twice in the same
                    # project, it's probably due to showing up in
                    # two branches.  Ignore subsequent
                    # definitions.
                    continue
                layout.addSemaphore(semaphore)

        project_template_parser = ProjectTemplateParser(tenant, layout)
        for config_template in data.project_templates:
            classes = TenantParser._getLoadClasses(tenant, config_template)
            if 'project-template' not in classes:
                continue
            with configuration_exceptions('project-template', config_template):
                layout.addProjectTemplate(project_template_parser.fromYaml(
                    config_template))

        project_parser = ProjectParser(tenant, layout, project_template_parser)
        for config_projects in data.projects.values():
            # Unlike other config classes, we expect multiple project
            # stanzas with the same name, so that a config repo can
            # define a project-pipeline and the project itself can
            # augment it.  To that end, config_project is a list of
            # each of the project stanzas.  Each one may be (should
            # be!) from a different repo, so filter them according to
            # the include/exclude rules before parsing them.
            filtered_projects = []
            for config_project in config_projects:
                classes = TenantParser._getLoadClasses(tenant, config_project)
                if 'project' in classes:
                    filtered_projects.append(config_project)

            if not filtered_projects:
                continue

            layout.addProjectConfig(project_parser.fromYaml(
                filtered_projects))

    @staticmethod
    def _parseLayout(base, tenant, data, scheduler, connections):
        # Don't call this method from dynamic reconfiguration because
        # it interacts with drivers and connections.
        layout = model.Layout(tenant)
        TenantParser.log.debug("Created layout id %s", layout.uuid)

        TenantParser._parseLayoutItems(layout, tenant, data,
                                       scheduler, connections)

        for pipeline in layout.pipelines.values():
            pipeline.manager._postConfig(layout)

        return layout


class ConfigLoader(object):
    log = logging.getLogger("zuul.ConfigLoader")

    def expandConfigPath(self, config_path):
        if config_path:
            config_path = os.path.expanduser(config_path)
        if not os.path.exists(config_path):
            raise Exception("Unable to read tenant config file at %s" %
                            config_path)
        return config_path

    def loadConfig(self, config_path, project_key_dir, scheduler, merger,
                   connections):
        abide = model.Abide()

        config_path = self.expandConfigPath(config_path)
        with open(config_path) as config_file:
            self.log.info("Loading configuration from %s" % (config_path,))
            data = yaml.safe_load(config_file)
        config = model.UnparsedAbideConfig()
        config.extend(data)
        base = os.path.dirname(os.path.realpath(config_path))

        for conf_tenant in config.tenants:
            # When performing a full reload, do not use cached data.
            tenant = TenantParser.fromYaml(
                base, project_key_dir, connections, scheduler, merger,
                conf_tenant, old_tenant=None)
            abide.tenants[tenant.name] = tenant
        return abide

    def reloadTenant(self, config_path, project_key_dir, scheduler,
                     merger, connections, abide, tenant):
        new_abide = model.Abide()
        new_abide.tenants = abide.tenants.copy()

        config_path = self.expandConfigPath(config_path)
        base = os.path.dirname(os.path.realpath(config_path))

        # When reloading a tenant only, use cached data if available.
        new_tenant = TenantParser.fromYaml(
            base, project_key_dir, connections, scheduler, merger,
            tenant.unparsed_config, old_tenant=tenant)
        new_abide.tenants[tenant.name] = new_tenant
        return new_abide

    def _loadDynamicProjectData(self, config, project, files, trusted, tenant):
        if trusted:
            branches = ['master']
        else:
            # Use the cached branch list; since this is a dynamic
            # reconfiguration there should not be any branch changes.
            branches = sorted(project.unparsed_branch_config.keys())
            if 'master' in branches:
                branches.remove('master')
                branches = ['master'] + branches

        for branch in branches:
            fns1 = []
            fns2 = []
            files_entry = files.connections.get(
                project.source.connection.connection_name, {}).get(
                    project.name, {}).get(branch)
            # If there is no files entry at all for this
            # project-branch, then use the cached config.
            if files_entry is None:
                if trusted:
                    incdata = project.unparsed_config
                else:
                    incdata = project.unparsed_branch_config.get(branch)
                if incdata:
                    config.extend(incdata)
                continue
            # Otherwise, do not use the cached config (even if the
            # files are empty as that likely means they were deleted).
            files_list = files_entry.keys()
            for fn in files_list:
                if fn.startswith("zuul.d/"):
                    fns1.append(fn)
                if fn.startswith(".zuul.d/"):
                    fns2.append(fn)
            fns = ["zuul.yaml"] + sorted(fns1) + [".zuul.yaml"] + sorted(fns2)
            incdata = None
            loaded = None
            for fn in fns:
                data = files.getFile(project.source.connection.connection_name,
                                     project.name, branch, fn)
                if data:
                    source_context = model.SourceContext(project, branch,
                                                         fn, trusted)
                    # Prevent mixing configuration source
                    conf_root = fn.split('/')[0]
                    if loaded and loaded != conf_root:
                        TenantParser.log.warning(
                            "Multiple configuration in %s" % source_context)
                        continue
                    loaded = conf_root

                    if trusted:
                        incdata = TenantParser._parseConfigProjectLayout(
                            data, source_context)
                    else:
                        incdata = TenantParser._parseUntrustedProjectLayout(
                            data, source_context)

                    config.extend(incdata)

    def createDynamicLayout(self, tenant, files,
                            include_config_projects=False,
                            scheduler=None, connections=None):
        if include_config_projects:
            config = model.UnparsedTenantConfig()
            for project in tenant.config_projects:
                self._loadDynamicProjectData(
                    config, project, files, True, tenant)
        else:
            config = tenant.config_projects_config.copy()
        for project in tenant.untrusted_projects:
            self._loadDynamicProjectData(config, project, files, False, tenant)

        layout = model.Layout(tenant)
        self.log.debug("Created layout id %s", layout.uuid)
        if not include_config_projects:
            # NOTE: the actual pipeline objects (complete with queues
            # and enqueued items) are copied by reference here.  This
            # allows our shadow dynamic configuration to continue to
            # interact with all the other changes, each of which may
            # have their own version of reality.  We do not support
            # creating, updating, or deleting pipelines in dynamic
            # layout changes.
            layout.pipelines = tenant.layout.pipelines

            # NOTE: the semaphore definitions are copied from the
            # static layout here. For semaphores there should be no
            # per patch max value but exactly one value at any
            # time. So we do not support dynamic semaphore
            # configuration changes.
            layout.semaphores = tenant.layout.semaphores
            skip_pipelines = skip_semaphores = True
        else:
            skip_pipelines = skip_semaphores = False

        TenantParser._parseLayoutItems(layout, tenant, config,
                                       scheduler, connections,
                                       skip_pipelines=skip_pipelines,
                                       skip_semaphores=skip_semaphores)

        return layout
