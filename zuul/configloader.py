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

import os
import logging
import six
import yaml

import voluptuous as vs

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


class NodeSetParser(object):
    @staticmethod
    def getSchema():
        node = {vs.Required('name'): str,
                vs.Required('image'): str,
                }

        nodeset = {vs.Required('name'): str,
                   vs.Required('nodes'): [node],
                   }

        return vs.Schema(nodeset)

    @staticmethod
    def fromYaml(layout, conf):
        NodeSetParser.getSchema()(conf)
        ns = model.NodeSet(conf['name'])
        for conf_node in as_list(conf['nodes']):
            node = model.Node(conf_node['name'], conf_node['image'])
            ns.addNode(node)
        return ns


class JobParser(object):
    @staticmethod
    def getSchema():
        swift_tmpurl = {vs.Required('name'): str,
                        'container': str,
                        'expiry': int,
                        'max_file_size': int,
                        'max-file-size': int,
                        'max_file_count': int,
                        'max-file-count': int,
                        'logserver_prefix': str,
                        'logserver-prefix': str,
                        }

        auth = {'secrets': to_list(str),
                'inherit': bool,
                'swift-tmpurl': to_list(swift_tmpurl),
                }

        node = {vs.Required('name'): str,
                vs.Required('image'): str,
                }

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
               '_source_project': model.Project,
               '_source_branch': vs.Any(str, None),
               }

        return vs.Schema(job)

    @staticmethod
    def fromYaml(layout, conf):
        JobParser.getSchema()(conf)
        job = model.Job(conf['name'])
        if 'auth' in conf:
            job.auth = conf.get('auth')
        if 'parent' in conf:
            parent = layout.getJob(conf['parent'])
            job.inheritFrom(parent)
        job.timeout = conf.get('timeout', job.timeout)
        job.workspace = conf.get('workspace', job.workspace)
        job.pre_run = as_list(conf.get('pre-run', job.pre_run))
        job.post_run = as_list(conf.get('post-run', job.post_run))
        job.voting = conf.get('voting', True)
        job.hold_following_changes = conf.get('hold-following-changes', False)
        job.mutex = conf.get('mutex', None)
        job.attempts = conf.get('attempts', 3)
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

        tags = conf.get('tags')
        if tags:
            # Tags are merged via a union rather than a
            # destructive copy because they are intended to
            # accumulate onto any previously applied tags from
            # metajobs.
            job.tags = job.tags.union(set(tags))
        # The source attributes may not be overridden -- they are
        # always supplied by the config loader.  They correspond to
        # the Project instance of the repo where it originated, and
        # the branch name.
        job.source_project = conf.get('_source_project')
        job.source_branch = conf.get('_source_branch')
        job.failure_message = conf.get('failure-message', job.failure_message)
        job.success_message = conf.get('success-message', job.success_message)
        job.failure_url = conf.get('failure-url', job.failure_url)
        job.success_url = conf.get('success-url', job.success_url)

        # If the definition for this job came from a project repo,
        # implicitly apply a branch matcher for the branch it was on.
        if job.source_branch:
            branches = [job.source_branch]
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


class ProjectTemplateParser(object):
    log = logging.getLogger("zuul.ProjectTemplateParser")

    @staticmethod
    def getSchema(layout):
        project_template = {vs.Required('name'): str}
        for p in layout.pipelines.values():
            project_template[p.name] = {'queue': str,
                                        'jobs': [vs.Any(str, dict)]}
        return vs.Schema(project_template)

    @staticmethod
    def fromYaml(layout, conf):
        ProjectTemplateParser.getSchema(layout)(conf)
        project_template = model.ProjectConfig(conf['name'])
        for pipeline in layout.pipelines.values():
            conf_pipeline = conf.get(pipeline.name)
            if not conf_pipeline:
                continue
            project_pipeline = model.ProjectPipelineConfig()
            project_template.pipelines[pipeline.name] = project_pipeline
            project_pipeline.queue_name = conf_pipeline.get('queue')
            project_pipeline.job_tree = ProjectTemplateParser._parseJobTree(
                layout, conf_pipeline.get('jobs', []))
        return project_template

    @staticmethod
    def _parseJobTree(layout, conf, tree=None):
        if not tree:
            tree = model.JobTree(None)
        for conf_job in conf:
            if isinstance(conf_job, six.string_types):
                tree.addJob(model.Job(conf_job))
            elif isinstance(conf_job, dict):
                # A dictionary in a job tree may override params, or
                # be the root of a sub job tree, or both.
                jobname, attrs = conf_job.items()[0]
                jobs = attrs.pop('jobs', None)
                if attrs:
                    # We are overriding params, so make a new job def
                    attrs['name'] = jobname
                    subtree = tree.addJob(JobParser.fromYaml(layout, attrs))
                else:
                    # Not overriding, so get existing job
                    subtree = tree.addJob(layout.getJob(jobname))

                if jobs:
                    # This is the root of a sub tree
                    ProjectTemplateParser._parseJobTree(layout, jobs, subtree)
            else:
                raise Exception("Job must be a string or dictionary")
        return tree


class ProjectParser(object):
    log = logging.getLogger("zuul.ProjectParser")

    @staticmethod
    def getSchema(layout):
        project = {vs.Required('name'): str,
                   'templates': [str]}
        for p in layout.pipelines.values():
            project[p.name] = {'queue': str,
                               'jobs': [vs.Any(str, dict)]}
        return vs.Schema(project)

    @staticmethod
    def fromYaml(layout, conf):
        # TODOv3(jeblair): This may need some branch-specific
        # configuration for in-repo configs.
        ProjectParser.getSchema(layout)(conf)
        conf_templates = conf.pop('templates', [])
        # The way we construct a project definition is by parsing the
        # definition as a template, then applying all of the
        # templates, including the newly parsed one, in order.
        project_template = ProjectTemplateParser.fromYaml(layout, conf)
        configs = [layout.project_templates[name] for name in conf_templates]
        configs.append(project_template)
        project = model.ProjectConfig(conf['name'])
        for pipeline in layout.pipelines.values():
            project_pipeline = model.ProjectPipelineConfig()
            project_pipeline.job_tree = model.JobTree(None)
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
                    project_pipeline.job_tree.inheritFrom(
                        template_pipeline.job_tree)
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
        for connection_name, connection in connections.connections.items():
            for dname, dmod in connection_drivers.get(dtype, {}).items():
                if connection.driver_name == dname:
                    schema[connection_name] = to_list(__import__(
                        connection_drivers[dtype][dname],
                        fromlist=['']).getSchema())

        # Standard drivers are always available and don't require a unique
        # (connection) name
        for dname, dmod in standard_drivers.get(dtype, {}).items():
            schema[dname] = to_list(__import__(
                standard_drivers[dtype][dname], fromlist=['']).getSchema())

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

        for trigger_name, trigger_config\
            in conf.get('trigger').items():
            trigger = connections.getTrigger(trigger_name, trigger_config)
            pipeline.triggers.append(trigger)

            # TODO: move
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
    def fromYaml(base, connections, scheduler, merger, conf):
        TenantParser.getSchema(connections)(conf)
        tenant = model.Tenant(conf['name'])
        unparsed_config = model.UnparsedTenantConfig()
        tenant.config_repos, tenant.project_repos = \
            TenantParser._loadTenantConfigRepos(connections, conf)
        tenant.config_repos_config, tenant.project_repos_config = \
            TenantParser._loadTenantInRepoLayouts(
                merger, connections, tenant.config_repos, tenant.project_repos)
        unparsed_config.extend(tenant.config_repos_config)
        unparsed_config.extend(tenant.project_repos_config)
        tenant.layout = TenantParser._parseLayout(base, unparsed_config,
                                                  scheduler, connections)
        tenant.layout.tenant = tenant
        return tenant

    @staticmethod
    def _loadTenantConfigRepos(connections, conf_tenant):
        config_repos = []
        project_repos = []

        for source_name, conf_source in conf_tenant.get('source', {}).items():
            source = connections.getSource(source_name)

            for conf_repo in conf_source.get('config-repos', []):
                project = source.getProject(conf_repo)
                config_repos.append((source, project))

            for conf_repo in conf_source.get('project-repos', []):
                project = source.getProject(conf_repo)
                project_repos.append((source, project))

        return config_repos, project_repos

    @staticmethod
    def _loadTenantInRepoLayouts(merger, connections, config_repos,
                                 project_repos):
        config_repos_config = model.UnparsedTenantConfig()
        project_repos_config = model.UnparsedTenantConfig()
        jobs = []

        for (source, project) in config_repos:
            # Get main config files.  These files are permitted the
            # full range of configuration.
            url = source.getGitUrl(project)
            job = merger.getFiles(project.name, url, 'master',
                                  files=['zuul.yaml', '.zuul.yaml'])
            job.project = project
            job.config_repo = True
            jobs.append(job)

        for (source, project) in project_repos:
            # Get in-project-repo config files which have a restricted
            # set of options.
            url = source.getGitUrl(project)
            # For each branch in the repo, get the zuul.yaml for that
            # branch.  Remember the branch and then implicitly add a
            # branch selector to each job there.  This makes the
            # in-repo configuration apply only to that branch.
            for branch in source.getProjectBranches(project):
                job = merger.getFiles(project.name, url, branch,
                                      files=['.zuul.yaml'])
                job.project = project
                job.branch = branch
                job.config_repo = False
                jobs.append(job)

        for job in jobs:
            # Note: this is an ordered list -- we wait for cat jobs to
            # complete in the order they were launched which is the
            # same order they were defined in the main config file.
            # This is important for correct inheritance.
            TenantParser.log.debug("Waiting for cat job %s" % (job,))
            job.wait()
            for fn in ['zuul.yaml', '.zuul.yaml']:
                if job.files.get(fn):
                    TenantParser.log.info(
                        "Loading configuration from %s/%s" %
                        (job.project, fn))
                    if job.config_repo:
                        incdata = TenantParser._parseConfigRepoLayout(
                            job.files[fn], job.project)
                        config_repos_config.extend(incdata)
                    else:
                        incdata = TenantParser._parseProjectRepoLayout(
                            job.files[fn], job.project, job.branch)
                        project_repos_config.extend(incdata)
                    job.project.unparsed_config = incdata
        return config_repos_config, project_repos_config

    @staticmethod
    def _parseConfigRepoLayout(data, project):
        # This is the top-level configuration for a tenant.
        config = model.UnparsedTenantConfig()
        config.extend(yaml.load(data), project)

        return config

    @staticmethod
    def _parseProjectRepoLayout(data, project, branch):
        # TODOv3(jeblair): this should implement some rules to protect
        # aspects of the config that should not be changed in-repo
        config = model.UnparsedTenantConfig()
        config.extend(yaml.load(data), project, branch)

        return config

    @staticmethod
    def _parseLayout(base, data, scheduler, connections):
        layout = model.Layout()

        for config_pipeline in data.pipelines:
            layout.addPipeline(PipelineParser.fromYaml(layout, connections,
                                                       scheduler,
                                                       config_pipeline))

        for config_nodeset in data.nodesets:
            layout.addNodeSet(NodeSetParser.fromYaml(layout, config_nodeset))

        for config_job in data.jobs:
            layout.addJob(JobParser.fromYaml(layout, config_job))

        for config_template in data.project_templates:
            layout.addProjectTemplate(ProjectTemplateParser.fromYaml(
                layout, config_template))

        for config_project in data.projects:
            layout.addProjectConfig(ProjectParser.fromYaml(
                layout, config_project))

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

    def loadConfig(self, config_path, scheduler, merger, connections):
        abide = model.Abide()

        config_path = self.expandConfigPath(config_path)
        with open(config_path) as config_file:
            self.log.info("Loading configuration from %s" % (config_path,))
            data = yaml.load(config_file)
        config = model.UnparsedAbideConfig()
        config.extend(data)
        base = os.path.dirname(os.path.realpath(config_path))

        for conf_tenant in config.tenants:
            tenant = TenantParser.fromYaml(base, connections, scheduler,
                                           merger, conf_tenant)
            abide.tenants[tenant.name] = tenant
        return abide

    def createDynamicLayout(self, tenant, files):
        config = tenant.config_repos_config.copy()
        for source, project in tenant.project_repos:
            # TODOv3(jeblair): config should be branch specific
            for branch in source.getProjectBranches(project):
                data = files.getFile(project.name, branch, '.zuul.yaml')
                if not data:
                    data = project.unparsed_config
                if not data:
                    continue
                incdata = TenantParser._parseProjectRepoLayout(
                    data, project, branch)
                config.extend(incdata)

        layout = model.Layout()
        # TODOv3(jeblair): copying the pipelines could be dangerous/confusing.
        layout.pipelines = tenant.layout.pipelines

        for config_job in config.jobs:
            layout.addJob(JobParser.fromYaml(layout, config_job))

        for config_template in config.project_templates:
            layout.addProjectTemplate(ProjectTemplateParser.fromYaml(
                layout, config_template))

        for config_project in config.projects:
            layout.addProjectConfig(ProjectParser.fromYaml(
                layout, config_project), update_pipeline=False)

        return layout
