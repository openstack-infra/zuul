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
import yaml

import voluptuous as vs

import model
import zuul.manager
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


class JobParser(object):
    @staticmethod
    def getSchema():
        # TODOv3(jeblair, jhesketh): move to auth
        swift = {vs.Required('name'): str,
                 'container': str,
                 'expiry': int,
                 'max_file_size': int,
                 'max-file-size': int,
                 'max_file_count': int,
                 'max-file-count': int,
                 'logserver_prefix': str,
                 'logserver-prefix': str,
                 }

        job = {vs.Required('name'): str,
               'parent': str,
               'queue-name': str,
               'failure-message': str,
               'success-message': str,
               'failure-url': str,
               'success-url': str,
               'voting': bool,
               'mutex': str,
               'tags': to_list(str),
               'branches': to_list(str),
               'files': to_list(str),
               'swift': to_list(swift),
               'irrelevant-files': to_list(str),
               'timeout': int,
               '_project_source': str,  # used internally
               '_project_name': str,  # used internally
               }

        return vs.Schema(job)

    @staticmethod
    def fromYaml(layout, conf):
        JobParser.getSchema()(conf)
        job = model.Job(conf['name'])
        if 'parent' in conf:
            parent = layout.getJob(conf['parent'])
            job.inheritFrom(parent)
        job.timeout = conf.get('timeout', job.timeout)
        job.workspace = conf.get('workspace', job.workspace)
        job.pre_run = as_list(conf.get('pre-run', job.pre_run))
        job.post_run = as_list(conf.get('post-run', job.post_run))
        job.voting = conf.get('voting', True)
        job.mutex = conf.get('mutex', None)
        tags = conf.get('tags')
        if tags:
            # Tags are merged via a union rather than a
            # destructive copy because they are intended to
            # accumulate onto any previously applied tags from
            # metajobs.
            job.tags = job.tags.union(set(tags))
        if not job.project_source:
            # Thes attributes may not be overidden -- the first
            # reference definition of a job is in the repo where it is
            # first defined.
            job.project_source = conf.get('_project_source')
            job.project_name = conf.get('_project_name')
        job.failure_message = conf.get('failure-message', job.failure_message)
        job.success_message = conf.get('success-message', job.success_message)
        job.failure_url = conf.get('failure-url', job.failure_url)
        job.success_url = conf.get('success-url', job.success_url)

        if 'branches' in conf:
            matchers = []
            for branch in as_list(conf['branches']):
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
            project_pipeline.queue_name = conf.get('queue')
            project_pipeline.job_tree = ProjectTemplateParser._parseJobTree(
                layout, conf_pipeline.get('jobs'))
        return project_template

    @staticmethod
    def _parseJobTree(layout, conf, tree=None):
        if not tree:
            tree = model.JobTree(None)
        for conf_job in conf:
            if isinstance(conf_job, basestring):
                tree.addJob(layout.getJob(conf_job))
            elif isinstance(conf_job, dict):
                # A dictionary in a job tree may override params, or
                # be the root of a sub job tree, or both.
                jobname, attrs = dict.items()[0]
                jobs = attrs.pop('jobs')
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
                ProjectParser.log.debug("Applying template %s to pipeline %s" %
                                        (template.name, pipeline.name))
                if pipeline.name in template.pipelines:
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
                statuses=to_list(require.get('status')),
                required_approvals=to_list(require.get('approval')),
                reject_approvals=to_list(reject.get('approval'))
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
        tenant_config = model.UnparsedTenantConfig()
        incdata = TenantParser._loadTenantInRepoLayouts(merger, connections,
                                                        conf)
        tenant_config.extend(incdata)
        tenant.layout = TenantParser._parseLayout(base, tenant_config,
                                                  scheduler, connections)
        return tenant

    @staticmethod
    def _loadTenantInRepoLayouts(merger, connections, conf_tenant):
        config = model.UnparsedTenantConfig()
        jobs = []
        for source_name, conf_source in conf_tenant.get('source', {}).items():
            source = connections.getSource(source_name)

            # Get main config files.  These files are permitted the
            # full range of configuration.
            for conf_repo in conf_source.get('config-repos', []):
                project = source.getProject(conf_repo)
                url = source.getGitUrl(project)
                job = merger.getFiles(project.name, url, 'master',
                                      files=['zuul.yaml', '.zuul.yaml'])
                job.project = project
                job.config_repo = True
                jobs.append(job)

            # Get in-project-repo config files which have a restricted
            # set of options.
            for conf_repo in conf_source.get('project-repos', []):
                project = source.getProject(conf_repo)
                url = source.getGitUrl(project)
                # TODOv3(jeblair): config should be branch specific
                job = merger.getFiles(project.name, url, 'master',
                                      files=['.zuul.yaml'])
                job.project = project
                job.config_repo = False
                jobs.append(job)

        for job in jobs:
            # Note: this is an ordered list -- we wait for cat jobs to
            # complete in the order they were launched which is the
            # same order they were defined in the main config file.
            # This is important for correct inheritence.
            TenantParser.log.debug("Waiting for cat job %s" % (job,))
            job.wait()
            for fn in ['zuul.yaml', '.zuul.yaml']:
                if job.files.get(fn):
                    TenantParser.log.info(
                        "Loading configuration from %s/%s" %
                        (job.project, fn))
                    if job.config_repo:
                        incdata = TenantParser._parseConfigRepoLayout(
                            job.files[fn], source_name, job.project.name)
                    else:
                        incdata = TenantParser._parseProjectRepoLayout(
                            job.files[fn], source_name, job.project.name)
                    config.extend(incdata)
        return config

    @staticmethod
    def _parseConfigRepoLayout(data, source_name, project_name):
        # This is the top-level configuration for a tenant.
        config = model.UnparsedTenantConfig()
        config.extend(yaml.load(data))

        # Remember where this job was defined
        for conf_job in config.jobs:
            conf_job['_project_source'] = source_name
            conf_job['_project_name'] = project_name

        return config

    @staticmethod
    def _parseProjectRepoLayout(data, source_name, project_name):
        # TODOv3(jeblair): this should implement some rules to protect
        # aspects of the config that should not be changed in-repo
        config = model.UnparsedTenantConfig()
        config.extend(yaml.load(data))

        # Remember where this job was defined
        for conf_job in config.jobs:
            conf_job['_project_source'] = source_name
            conf_job['_project_name'] = project_name

        return config

    @staticmethod
    def _parseLayout(base, data, scheduler, connections):
        layout = model.Layout()

        for config_pipeline in data.pipelines:
            layout.addPipeline(PipelineParser.fromYaml(layout, connections,
                                                       scheduler,
                                                       config_pipeline))

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

    def loadConfig(self, config_path, scheduler, merger, connections):
        abide = model.Abide()

        if config_path:
            config_path = os.path.expanduser(config_path)
            if not os.path.exists(config_path):
                raise Exception("Unable to read tenant config file at %s" %
                                config_path)
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
