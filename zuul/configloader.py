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

from contextlib import contextmanager
import copy
import os
import logging
import six
import yaml
import pprint
import textwrap

import voluptuous as vs

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from zuul import model
import zuul.manager.dependent
import zuul.manager.independent
from zuul import change_matcher


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


def indent(s):
    return '\n'.join(['  ' + x for x in s.split('\n')])


@contextmanager
def configuration_exceptions(stanza, conf):
    try:
        yield
    except vs.Invalid as e:
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

        The error appears in a {stanza} stanza with the content:

        {content}

        {start_mark}""")

        m = m.format(intro=intro,
                     error=indent(str(e)),
                     stanza=stanza,
                     content=indent(pprint.pformat(conf)),
                     start_mark=str(start_mark))
        raise ConfigurationSyntaxError(m)


class ZuulSafeLoader(yaml.SafeLoader):
    zuul_node_types = frozenset(('job', 'nodeset', 'secret', 'pipeline',
                                 'project', 'project-template'))

    def __init__(self, stream, context):
        super(ZuulSafeLoader, self).__init__(stream)
        self.name = str(context)
        self.zuul_context = context

    def construct_mapping(self, node, deep=False):
        r = super(ZuulSafeLoader, self).construct_mapping(node, deep)
        keys = frozenset(r.keys())
        if len(keys) == 1 and keys.intersection(self.zuul_node_types):
            d = r.values()[0]
            if isinstance(d, dict):
                d['_start_mark'] = node.start_mark
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


class EncryptedPKCS1(yaml.YAMLObject):
    yaml_tag = u'!encrypted/pkcs1'
    yaml_loader = yaml.SafeLoader

    def __init__(self, ciphertext):
        self.ciphertext = ciphertext

    @classmethod
    def from_yaml(cls, loader, node):
        return cls(node.value)


class NodeSetParser(object):
    @staticmethod
    def getSchema():
        node = {vs.Required('name'): str,
                vs.Required('image'): str,
                }

        nodeset = {vs.Required('name'): str,
                   vs.Required('nodes'): [node],
                   '_source_context': model.SourceContext,
                   '_start_mark': yaml.Mark,
                   }

        return vs.Schema(nodeset)

    @staticmethod
    def fromYaml(layout, conf):
        with configuration_exceptions('nodeset', conf):
            NodeSetParser.getSchema()(conf)
        ns = model.NodeSet(conf['name'])
        for conf_node in as_list(conf['nodes']):
            node = model.Node(conf_node['name'], conf_node['image'])
            ns.addNode(node)
        return ns


class SecretParser(object):
    @staticmethod
    def getSchema():
        data = {str: vs.Any(str, EncryptedPKCS1)}

        secret = {vs.Required('name'): str,
                  vs.Required('data'): data,
                  '_source_context': model.SourceContext,
                  '_start_mark': yaml.Mark,
                  }

        return vs.Schema(secret)

    @staticmethod
    def fromYaml(layout, conf):
        with configuration_exceptions('secret', conf):
            SecretParser.getSchema()(conf)
        s = model.Secret(conf['name'])
        s.secret_data = conf['data']
        return s


class JobParser(object):
    @staticmethod
    def getSchema():
        auth = {'secrets': to_list(str),
                'inherit': bool,
                }

        node = {vs.Required('name'): str,
                vs.Required('image'): str,
                }

        zuul_role = {vs.Required('zuul'): str,
                     'name': str}

        galaxy_role = {vs.Required('galaxy'): str,
                       'name': str}

        role = vs.Any(zuul_role, galaxy_role)

        job = {vs.Required('name'): str,
               'parent': str,
               'queue-name': str,
               'failure-message': str,
               'success-message': str,
               'failure-url': str,
               'success-url': str,
               'hold-following-changes': bool,
               'voting': bool,
               'mutex': str,
               'tags': to_list(str),
               'branches': to_list(str),
               'files': to_list(str),
               'auth': to_list(auth),
               'irrelevant-files': to_list(str),
               'nodes': vs.Any([node], str),
               'timeout': int,
               'attempts': int,
               'pre-run': to_list(str),
               'post-run': to_list(str),
               'run': str,
               '_source_context': model.SourceContext,
               '_start_mark': yaml.Mark,
               'roles': to_list(role),
               'repos': to_list(str),
               'vars': dict,
               'dependencies': to_list(str),
               }

        return vs.Schema(job)

    simple_attributes = [
        'timeout',
        'workspace',
        'voting',
        'hold-following-changes',
        'mutex',
        'attempts',
        'failure-message',
        'success-message',
        'failure-url',
        'success-url',
    ]

    @staticmethod
    def fromYaml(tenant, layout, conf):
        with configuration_exceptions('job', conf):
            JobParser.getSchema()(conf)

        # NB: The default detection system in the Job class requires
        # that we always assign values directly rather than modifying
        # them (e.g., "job.run = ..." rather than
        # "job.run.append(...)").

        job = model.Job(conf['name'])
        job.source_context = conf.get('_source_context')
        if 'auth' in conf:
            job.auth = conf.get('auth')

        if 'parent' in conf:
            parent = layout.getJob(conf['parent'])
            job.inheritFrom(parent)

        for pre_run_name in as_list(conf.get('pre-run')):
            full_pre_run_name = os.path.join('playbooks', pre_run_name)
            pre_run = model.PlaybookContext(job.source_context,
                                            full_pre_run_name)
            job.pre_run = job.pre_run + (pre_run,)
        for post_run_name in as_list(conf.get('post-run')):
            full_post_run_name = os.path.join('playbooks', post_run_name)
            post_run = model.PlaybookContext(job.source_context,
                                             full_post_run_name)
            job.post_run = (post_run,) + job.post_run
        if 'run' in conf:
            run_name = os.path.join('playbooks', conf['run'])
            run = model.PlaybookContext(job.source_context, run_name)
            job.run = (run,)
        else:
            run_name = os.path.join('playbooks', job.name)
            run = model.PlaybookContext(job.source_context, run_name)
            job.implied_run = (run,) + job.implied_run

        for k in JobParser.simple_attributes:
            a = k.replace('-', '_')
            if k in conf:
                setattr(job, a, conf[k])
        if 'nodes' in conf:
            conf_nodes = conf['nodes']
            if isinstance(conf_nodes, six.string_types):
                # This references an existing named nodeset in the layout.
                ns = layout.nodesets[conf_nodes]
            else:
                ns = model.NodeSet()
                for conf_node in conf_nodes:
                    node = model.Node(conf_node['name'], conf_node['image'])
                    ns.addNode(node)
            job.nodeset = ns

        if 'repos' in conf:
            # Accumulate repos in a set so that job inheritance
            # is additive.
            job.repos = job.repos.union(set(conf.get('repos', [])))

        tags = conf.get('tags')
        if tags:
            # Tags are merged via a union rather than a
            # destructive copy because they are intended to
            # accumulate onto any previously applied tags.
            job.tags = job.tags.union(set(tags))

        job.dependencies = frozenset(as_list(conf.get('dependencies')))

        roles = []
        for role in conf.get('roles', []):
            if 'zuul' in role:
                r = JobParser._makeZuulRole(tenant, job, role)
                if r:
                    roles.append(r)
        job.roles = job.roles.union(set(roles))

        variables = conf.get('vars', None)
        if variables:
            job.updateVariables(variables)

        # If the definition for this job came from a project repo,
        # implicitly apply a branch matcher for the branch it was on.
        if (not job.source_context.trusted):
            branches = [job.source_context.branch]
        elif 'branches' in conf:
            branches = as_list(conf['branches'])
        else:
            branches = None
        if branches:
            matchers = []
            for branch in branches:
                matchers.append(change_matcher.BranchMatcher(branch))
            job.branch_matcher = change_matcher.MatchAny(matchers)
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

        # TODOv3(jeblair): this limits roles to the same
        # source; we should remove that limitation.
        source = job.source_context.project.connection_name
        (trusted, project) = tenant.getRepo(source, role['zuul'])
        if project is None:
            return None

        return model.ZuulRole(role.get('name', name), source,
                              project.name, trusted)


class ProjectTemplateParser(object):
    log = logging.getLogger("zuul.ProjectTemplateParser")

    @staticmethod
    def getSchema(layout):
        project_template = {
            vs.Required('name'): str,
            'merge-mode': vs.Any(
                'merge', 'merge-resolve',
                'cherry-pick'),
            '_source_context': model.SourceContext,
            '_start_mark': yaml.Mark,
        }

        for p in layout.pipelines.values():
            project_template[p.name] = {'queue': str,
                                        'jobs': [vs.Any(str, dict)]}
        return vs.Schema(project_template)

    @staticmethod
    def fromYaml(tenant, layout, conf):
        with configuration_exceptions('project or project-template', conf):
            ProjectTemplateParser.getSchema(layout)(conf)
        # Make a copy since we modify this later via pop
        conf = copy.deepcopy(conf)
        project_template = model.ProjectConfig(conf['name'])
        source_context = conf['_source_context']
        start_mark = conf['_start_mark']
        for pipeline in layout.pipelines.values():
            conf_pipeline = conf.get(pipeline.name)
            if not conf_pipeline:
                continue
            project_pipeline = model.ProjectPipelineConfig()
            project_template.pipelines[pipeline.name] = project_pipeline
            project_pipeline.queue_name = conf_pipeline.get('queue')
            ProjectTemplateParser._parseJobList(
                tenant, layout, conf_pipeline.get('jobs', []),
                source_context, start_mark, project_pipeline.job_list)
        return project_template

    @staticmethod
    def _parseJobList(tenant, layout, conf, source_context,
                      start_mark, job_list):
        for conf_job in conf:
            if isinstance(conf_job, six.string_types):
                job = model.Job(conf_job)
                job_list.addJob(job)
            elif isinstance(conf_job, dict):
                # A dictionary in a job tree may override params
                jobname, attrs = conf_job.items()[0]
                if attrs:
                    # We are overriding params, so make a new job def
                    attrs['name'] = jobname
                    attrs['_source_context'] = source_context
                    attrs['_start_mark'] = start_mark
                    job_list.addJob(JobParser.fromYaml(tenant, layout, attrs))
                else:
                    # Not overriding, so add a blank job
                    job = model.Job(jobname)
                    job_list.addJob(job)
            else:
                raise Exception("Job must be a string or dictionary")


class ProjectParser(object):
    log = logging.getLogger("zuul.ProjectParser")

    @staticmethod
    def getSchema(layout):
        project = {
            vs.Required('name'): str,
            'templates': [str],
            'merge-mode': vs.Any('merge', 'merge-resolve',
                                 'cherry-pick'),
            '_source_context': model.SourceContext,
            '_start_mark': yaml.Mark,
        }

        for p in layout.pipelines.values():
            project[p.name] = {'queue': str,
                               'jobs': [vs.Any(str, dict)]}
        return vs.Schema(project)

    @staticmethod
    def fromYaml(tenant, layout, conf_list):
        for conf in conf_list:
            with configuration_exceptions('project', conf):
                ProjectParser.getSchema(layout)(conf)
        project = model.ProjectConfig(conf_list[0]['name'])

        configs = []
        for conf in conf_list:
            # Make a copy since we modify this later via pop
            conf = copy.deepcopy(conf)
            conf_templates = conf.pop('templates', [])
            # The way we construct a project definition is by parsing the
            # definition as a template, then applying all of the
            # templates, including the newly parsed one, in order.
            project_template = ProjectTemplateParser.fromYaml(
                tenant, layout, conf)
            configs.extend([layout.project_templates[name]
                            for name in conf_templates])
            configs.append(project_template)
            mode = conf.get('merge-mode')
            if mode and project.merge_mode is None:
                # Set the merge mode to the first one that we find and
                # ignore subsequent settings.
                project.merge_mode = model.MERGER_MAP[mode]
        if project.merge_mode is None:
            # If merge mode was not specified in any project stanza,
            # set it to the default.
            project.merge_mode = model.MERGER_MAP['merge-resolve']
        for pipeline in layout.pipelines.values():
            project_pipeline = model.ProjectPipelineConfig()
            queue_name = None
            # For every template, iterate over the job tree and replace or
            # create the jobs in the final definition as needed.
            pipeline_defined = False
            for template in configs:
                if pipeline.name in template.pipelines:
                    ProjectParser.log.debug(
                        "Applying template %s to pipeline %s" %
                        (template.name, pipeline.name))
                    pipeline_defined = True
                    template_pipeline = template.pipelines[pipeline.name]
                    project_pipeline.job_list.inheritFrom(
                        template_pipeline.job_list)
                    if template_pipeline.queue_name:
                        queue_name = template_pipeline.queue_name
            if queue_name:
                project_pipeline.queue_name = queue_name
            if pipeline_defined:
                project.pipelines[pipeline.name] = project_pipeline

        return project


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

        approval = vs.Schema({'username': str,
                              'email-filter': str,
                              'email': str,
                              'older-than': str,
                              'newer-than': str,
                              }, extra=True)

        require = {'approval': to_list(approval),
                   'open': bool,
                   'current-patchset': bool,
                   'status': to_list(str)}

        reject = {'approval': to_list(approval)}

        window = vs.All(int, vs.Range(min=0))
        window_floor = vs.All(int, vs.Range(min=1))
        window_type = vs.Any('linear', 'exponential')
        window_factor = vs.All(int, vs.Range(min=1))

        pipeline = {vs.Required('name'): str,
                    vs.Required('manager'): manager,
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
                        vs.All(int, vs.Range(min=1)),
                    'window': window,
                    'window-floor': window_floor,
                    'window-increase-type': window_type,
                    'window-increase-factor': window_factor,
                    'window-decrease-type': window_type,
                    'window-decrease-factor': window_factor,
                    '_source_context': model.SourceContext,
                    '_start_mark': yaml.Mark,
                    }
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

        pipeline.source = connections.getSource(conf['source'])

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

        if 'require' in conf or 'reject' in conf:
            require = conf.get('require', {})
            reject = conf.get('reject', {})
            f = model.ChangeishFilter(
                open=require.get('open'),
                current_patchset=require.get('current-patchset'),
                statuses=as_list(require.get('status')),
                required_approvals=as_list(require.get('approval')),
                reject_approvals=as_list(reject.get('approval'))
            )
            manager.changeish_filters.append(f)

        for trigger_name, trigger_config in conf.get('trigger').items():
            trigger = connections.getTrigger(trigger_name, trigger_config)
            pipeline.triggers.append(trigger)

            manager.event_filters += trigger.getEventFilters(
                conf['trigger'][trigger_name])

        return pipeline


class TenantParser(object):
    log = logging.getLogger("zuul.TenantParser")

    tenant_source = vs.Schema({'config-repos': [str],
                               'project-repos': [str]})

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
                  'source': TenantParser.validateTenantSources(connections)}
        return vs.Schema(tenant)

    @staticmethod
    def fromYaml(base, project_key_dir, connections, scheduler, merger, conf,
                 cached):
        TenantParser.getSchema(connections)(conf)
        tenant = model.Tenant(conf['name'])
        tenant.unparsed_config = conf
        unparsed_config = model.UnparsedTenantConfig()
        tenant.config_repos, tenant.project_repos = \
            TenantParser._loadTenantConfigRepos(
                project_key_dir, connections, conf)
        for source, repo in tenant.config_repos:
            tenant.addConfigRepo(source, repo)
        for source, repo in tenant.project_repos:
            tenant.addProjectRepo(source, repo)
        tenant.config_repos_config, tenant.project_repos_config = \
            TenantParser._loadTenantInRepoLayouts(merger, connections,
                                                  tenant.config_repos,
                                                  tenant.project_repos,
                                                  cached)
        unparsed_config.extend(tenant.config_repos_config)
        unparsed_config.extend(tenant.project_repos_config)
        tenant.layout = TenantParser._parseLayout(base, tenant,
                                                  unparsed_config,
                                                  scheduler,
                                                  connections)
        tenant.layout.tenant = tenant
        return tenant

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
            os.makedirs(key_dir)

        TenantParser.log.info(
            "Generating RSA keypair for project %s" % (project.name,)
        )

        # Generate private RSA key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        # Serialize private key
        pem_private_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        TenantParser.log.info(
            "Saving RSA keypair for project %s to %s" % (
                project.name, project.private_key_file)
        )

        # Dump keys to filesystem
        with open(project.private_key_file, 'wb') as f:
            f.write(pem_private_key)

    @staticmethod
    def _loadKeys(project):
        # Check the key files specified are there
        if not os.path.isfile(project.private_key_file):
            raise Exception(
                'Private key file {0} not found'.format(
                    project.private_key_file))

        # Load private key
        with open(project.private_key_file, "rb") as f:
            project.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )

        # Extract public key from private
        project.public_key = project.private_key.public_key()

    @staticmethod
    def _loadTenantConfigRepos(project_key_dir, connections, conf_tenant):
        config_repos = []
        project_repos = []

        for source_name, conf_source in conf_tenant.get('source', {}).items():
            source = connections.getSource(source_name)

            for conf_repo in conf_source.get('config-repos', []):
                project = source.getProject(conf_repo)
                TenantParser._loadProjectKeys(
                    project_key_dir, source_name, project)
                config_repos.append((source, project))

            for conf_repo in conf_source.get('project-repos', []):
                project = source.getProject(conf_repo)
                TenantParser._loadProjectKeys(
                    project_key_dir, source_name, project)
                project_repos.append((source, project))

        return config_repos, project_repos

    @staticmethod
    def _loadTenantInRepoLayouts(merger, connections, config_repos,
                                 project_repos, cached):
        config_repos_config = model.UnparsedTenantConfig()
        project_repos_config = model.UnparsedTenantConfig()
        jobs = []

        for (source, project) in config_repos:
            # If we have cached data (this is a reconfiguration) use it.
            if cached and project.unparsed_config:
                TenantParser.log.info(
                    "Loading previously parsed configuration from %s" %
                    (project,))
                config_repos_config.extend(project.unparsed_config)
                continue
            # Otherwise, prepare an empty unparsed config object to
            # hold cached data later.
            project.unparsed_config = model.UnparsedTenantConfig()
            # Get main config files.  These files are permitted the
            # full range of configuration.
            url = source.getGitUrl(project)
            job = merger.getFiles(project.name, url, 'master',
                                  files=['zuul.yaml', '.zuul.yaml'])
            job.source_context = model.SourceContext(project, 'master',
                                                     '', True)
            jobs.append(job)

        for (source, project) in project_repos:
            # If we have cached data (this is a reconfiguration) use it.
            if cached and project.unparsed_config:
                TenantParser.log.info(
                    "Loading previously parsed configuration from %s" %
                    (project,))
                project_repos_config.extend(project.unparsed_config)
                continue
            # Otherwise, prepare an empty unparsed config object to
            # hold cached data later.
            project.unparsed_config = model.UnparsedTenantConfig()
            # Get in-project-repo config files which have a restricted
            # set of options.
            url = source.getGitUrl(project)
            # For each branch in the repo, get the zuul.yaml for that
            # branch.  Remember the branch and then implicitly add a
            # branch selector to each job there.  This makes the
            # in-repo configuration apply only to that branch.
            for branch in source.getProjectBranches(project):
                project.unparsed_branch_config[branch] = \
                    model.UnparsedTenantConfig()
                job = merger.getFiles(project.name, url, branch,
                                      files=['.zuul.yaml'])
                job.source_context = model.SourceContext(
                    project, branch, '', False)
                jobs.append(job)

        for job in jobs:
            # Note: this is an ordered list -- we wait for cat jobs to
            # complete in the order they were executed which is the
            # same order they were defined in the main config file.
            # This is important for correct inheritance.
            TenantParser.log.debug("Waiting for cat job %s" % (job,))
            job.wait()
            loaded = False
            for fn in ['zuul.yaml', '.zuul.yaml']:
                if job.files.get(fn):
                    # Don't load from more than one file in a repo-branch
                    if loaded:
                        TenantParser.log.warning(
                            "Multiple configuration files in %s" %
                            (job.source_context,))
                        continue
                    loaded = True
                    job.source_context.path = fn
                    TenantParser.log.info(
                        "Loading configuration from %s" %
                        (job.source_context,))
                    project = job.source_context.project
                    branch = job.source_context.branch
                    if job.source_context.trusted:
                        incdata = TenantParser._parseConfigRepoLayout(
                            job.files[fn], job.source_context)
                        config_repos_config.extend(incdata)
                    else:
                        incdata = TenantParser._parseProjectRepoLayout(
                            job.files[fn], job.source_context)
                        project_repos_config.extend(incdata)
                    project.unparsed_config.extend(incdata)
                    if branch in project.unparsed_branch_config:
                        project.unparsed_branch_config[branch].extend(incdata)
        return config_repos_config, project_repos_config

    @staticmethod
    def _parseConfigRepoLayout(data, source_context):
        # This is the top-level configuration for a tenant.
        config = model.UnparsedTenantConfig()
        config.extend(safe_load_yaml(data, source_context))
        return config

    @staticmethod
    def _parseProjectRepoLayout(data, source_context):
        # TODOv3(jeblair): this should implement some rules to protect
        # aspects of the config that should not be changed in-repo
        config = model.UnparsedTenantConfig()
        config.extend(safe_load_yaml(data, source_context))
        return config

    @staticmethod
    def _parseLayout(base, tenant, data, scheduler, connections):
        layout = model.Layout()

        for config_pipeline in data.pipelines:
            layout.addPipeline(PipelineParser.fromYaml(layout, connections,
                                                       scheduler,
                                                       config_pipeline))

        for config_nodeset in data.nodesets:
            layout.addNodeSet(NodeSetParser.fromYaml(layout, config_nodeset))

        for config_secret in data.secrets:
            layout.addSecret(SecretParser.fromYaml(layout, config_secret))

        for config_job in data.jobs:
            layout.addJob(JobParser.fromYaml(tenant, layout, config_job))

        for config_template in data.project_templates:
            layout.addProjectTemplate(ProjectTemplateParser.fromYaml(
                tenant, layout, config_template))

        for config_project in data.projects.values():
            layout.addProjectConfig(ProjectParser.fromYaml(
                tenant, layout, config_project))

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
                conf_tenant, cached=False)
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
            tenant.unparsed_config, cached=True)
        new_abide.tenants[tenant.name] = new_tenant
        return new_abide

    def _loadDynamicProjectData(self, config, source, project, files,
                                config_repo):
        for branch in source.getProjectBranches(project):
            data = None
            if config_repo:
                fn = 'zuul.yaml'
                data = files.getFile(project.name, branch, fn)
            if not data:
                fn = '.zuul.yaml'
                data = files.getFile(project.name, branch, fn)
            if data:
                source_context = model.SourceContext(project, branch,
                                                     fn, config_repo)
                if config_repo:
                    incdata = TenantParser._parseConfigRepoLayout(
                        data, source_context)
                else:
                    incdata = TenantParser._parseProjectRepoLayout(
                        data, source_context)
            else:
                incdata = project.unparsed_branch_config.get(branch)
            if not incdata:
                continue
            config.extend(incdata)

    def createDynamicLayout(self, tenant, files, include_config_repos=False):
        if include_config_repos:
            config = model.UnparsedTenantConfig()
            for source, project in tenant.config_repos:
                self._loadDynamicProjectData(config, source, project,
                                             files, True)
        else:
            config = tenant.config_repos_config.copy()
        for source, project in tenant.project_repos:
            self._loadDynamicProjectData(config, source, project,
                                         files, False)

        layout = model.Layout()
        # NOTE: the actual pipeline objects (complete with queues and
        # enqueued items) are copied by reference here.  This allows
        # our shadow dynamic configuration to continue to interact
        # with all the other changes, each of which may have their own
        # version of reality.  We do not support creating, updating,
        # or deleting pipelines in dynamic layout changes.
        layout.pipelines = tenant.layout.pipelines

        for config_job in config.jobs:
            layout.addJob(JobParser.fromYaml(tenant, layout, config_job))

        for config_template in config.project_templates:
            layout.addProjectTemplate(ProjectTemplateParser.fromYaml(
                tenant, layout, config_template))

        for config_project in config.projects.values():
            layout.addProjectConfig(ProjectParser.fromYaml(
                tenant, layout, config_project))
        return layout
