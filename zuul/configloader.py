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


def extend_dict(a, b):
    """Extend dictionary a (which will be modified in place) with the
       contents of b.  This is designed for Zuul yaml files which are
       typically dictionaries of lists of dictionaries, e.g.,
       {'pipelines': ['name': 'gate']}.  If two such dictionaries each
       define a pipeline, the result will be a single dictionary with
       a pipelines entry whose value is a two-element list."""

    for k, v in b.items():
        if k not in a:
            a[k] = v
        elif isinstance(v, dict) and isinstance(a[k], dict):
            extend_dict(a[k], v)
        elif isinstance(v, list) and isinstance(a[k], list):
            a[k] += v
        elif isinstance(v, list):
            a[k] = [a[k]] + v
        elif isinstance(a[k], list):
            a[k] += [v]
        else:
            raise Exception("Unhandled case in extend_dict at %s" % (k,))


def deep_format(obj, paramdict):
    """Apply the paramdict via str.format() to all string objects found within
       the supplied obj. Lists and dicts are traversed recursively.

       Borrowed from Jenkins Job Builder project"""
    if isinstance(obj, str):
        ret = obj.format(**paramdict)
    elif isinstance(obj, list):
        ret = []
        for item in obj:
            ret.append(deep_format(item, paramdict))
    elif isinstance(obj, dict):
        ret = {}
        for item in obj:
            exp_item = item.format(**paramdict)

            ret[exp_item] = deep_format(obj[item], paramdict)
    else:
        ret = obj
    return ret


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
               'branches': to_list(str),
               'files': to_list(str),
               'swift': to_list(swift),
               'irrelevant-files': to_list(str),
               'timeout': int,
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


class AbideValidator(object):
    tenant_source = vs.Schema({'repos': [str]})

    def validateTenantSources(self, connections):
        def v(value, path=[]):
            if isinstance(value, dict):
                for k, val in value.items():
                    connections.getSource(k)
                    self.validateTenantSource(val, path + [k])
            else:
                raise vs.Invalid("Invalid tenant source", path)
        return v

    def validateTenantSource(self, value, path=[]):
        self.tenant_source(value)

    def getSchema(self, connections=None):
        tenant = {vs.Required('name'): str,
                  'include': to_list(str),
                  'source': self.validateTenantSources(connections)}

        schema = vs.Schema({'tenants': [tenant]})

        return schema

    def validate(self, data, connections=None):
        schema = self.getSchema(connections)
        schema(data)


class ConfigLoader(object):
    log = logging.getLogger("zuul.ConfigLoader")

    # A set of reporter configuration keys to action mapping
    reporter_actions = {
        'start': 'start_actions',
        'success': 'success_actions',
        'failure': 'failure_actions',
        'merge-failure': 'merge_failure_actions',
        'disabled': 'disabled_actions',
    }

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
        base = os.path.dirname(os.path.realpath(config_path))

        validator = AbideValidator()
        validator.validate(data, connections)

        for conf_tenant in data['tenants']:
            tenant = model.Tenant(conf_tenant['name'])
            abide.tenants[tenant.name] = tenant
            tenant_config = {}
            for fn in conf_tenant.get('include', []):
                if not os.path.isabs(fn):
                    fn = os.path.join(base, fn)
                fn = os.path.expanduser(fn)
                with open(fn) as config_file:
                    self.log.info("Loading configuration from %s" % (fn,))
                    incdata = yaml.load(config_file)
                    extend_dict(tenant_config, incdata)
            incdata = self._loadTenantInRepoLayouts(merger, connections,
                                                    conf_tenant)
            extend_dict(tenant_config, incdata)
            tenant.layout = self._parseLayout(base, tenant_config,
                                              scheduler, connections)
        return abide

    def _parseLayout(self, base, data, scheduler, connections):
        layout = model.Layout()

        # TODOv3(jeblair): add validation
        # validator = layoutvalidator.LayoutValidator()
        # validator.validate(data, connections)

        config_env = {}
        for include in data.get('includes', []):
            if 'python-file' in include:
                fn = include['python-file']
                if not os.path.isabs(fn):
                    fn = os.path.join(base, fn)
                fn = os.path.expanduser(fn)
                execfile(fn, config_env)

        for conf_pipeline in data.get('pipelines', []):
            pipeline = model.Pipeline(conf_pipeline['name'], layout)
            pipeline.description = conf_pipeline.get('description')

            pipeline.source = connections.getSource(conf_pipeline['source'])

            precedence = model.PRECEDENCE_MAP[conf_pipeline.get('precedence')]
            pipeline.precedence = precedence
            pipeline.failure_message = conf_pipeline.get('failure-message',
                                                         "Build failed.")
            pipeline.merge_failure_message = conf_pipeline.get(
                'merge-failure-message', "Merge Failed.\n\nThis change or one "
                "of its cross-repo dependencies was unable to be "
                "automatically merged with the current state of its "
                "repository. Please rebase the change and upload a new "
                "patchset.")
            pipeline.success_message = conf_pipeline.get('success-message',
                                                         "Build succeeded.")
            pipeline.footer_message = conf_pipeline.get('footer-message', "")
            pipeline.dequeue_on_new_patchset = conf_pipeline.get(
                'dequeue-on-new-patchset', True)
            pipeline.ignore_dependencies = conf_pipeline.get(
                'ignore-dependencies', False)

            for conf_key, action in self.reporter_actions.items():
                reporter_set = []
                if conf_pipeline.get(conf_key):
                    for reporter_name, params \
                        in conf_pipeline.get(conf_key).items():
                        reporter = connections.getReporter(reporter_name,
                                                           params)
                        reporter.setAction(conf_key)
                        reporter_set.append(reporter)
                setattr(pipeline, action, reporter_set)

            # If merge-failure actions aren't explicit, use the failure actions
            if not pipeline.merge_failure_actions:
                pipeline.merge_failure_actions = pipeline.failure_actions

            pipeline.disable_at = conf_pipeline.get(
                'disable-after-consecutive-failures', None)

            pipeline.window = conf_pipeline.get('window', 20)
            pipeline.window_floor = conf_pipeline.get('window-floor', 3)
            pipeline.window_increase_type = conf_pipeline.get(
                'window-increase-type', 'linear')
            pipeline.window_increase_factor = conf_pipeline.get(
                'window-increase-factor', 1)
            pipeline.window_decrease_type = conf_pipeline.get(
                'window-decrease-type', 'exponential')
            pipeline.window_decrease_factor = conf_pipeline.get(
                'window-decrease-factor', 2)

            manager_name = conf_pipeline['manager']
            if manager_name == 'dependent':
                manager = zuul.manager.dependent.DependentPipelineManager(
                    scheduler, pipeline)
            elif manager_name == 'independent':
                manager = zuul.manager.independent.IndependentPipelineManager(
                    scheduler, pipeline)

            pipeline.setManager(manager)
            layout.pipelines[conf_pipeline['name']] = pipeline

            if 'require' in conf_pipeline or 'reject' in conf_pipeline:
                require = conf_pipeline.get('require', {})
                reject = conf_pipeline.get('reject', {})
                f = model.ChangeishFilter(
                    open=require.get('open'),
                    current_patchset=require.get('current-patchset'),
                    statuses=to_list(require.get('status')),
                    required_approvals=to_list(require.get('approval')),
                    reject_approvals=to_list(reject.get('approval'))
                )
                manager.changeish_filters.append(f)

            for trigger_name, trigger_config\
                in conf_pipeline.get('trigger').items():
                trigger = connections.getTrigger(trigger_name, trigger_config)
                pipeline.triggers.append(trigger)

                # TODO: move
                manager.event_filters += trigger.getEventFilters(
                    conf_pipeline['trigger'][trigger_name])

        for config_job in data.get('jobs', []):
            layout.addJob(JobParser.fromYaml(layout, config_job))

        for config_template in data.get('project-templates', []):
            layout.addProjectTemplate(ProjectTemplateParser.fromYaml(
                layout, config_template))

        for config_project in data.get('projects', []):
            layout.addProjectConfig(ProjectParser.fromYaml(
                layout, config_project))

        for pipeline in layout.pipelines.values():
            pipeline.manager._postConfig(layout)

        return layout

    def _loadTenantInRepoLayouts(self, merger, connections, conf_tenant):
        config = {}
        jobs = []
        for source_name, conf_source in conf_tenant.get('source', {}).items():
            source = connections.getSource(source_name)
            for conf_repo in conf_source.get('repos'):
                project = source.getProject(conf_repo)
                url = source.getGitUrl(project)
                # TODOv3(jeblair): config should be branch specific
                job = merger.getFiles(project.name, url, 'master',
                                      files=['.zuul.yaml'])
                job.project = project
                jobs.append(job)
        for job in jobs:
            self.log.debug("Waiting for cat job %s" % (job,))
            job.wait()
            if job.files.get('.zuul.yaml'):
                self.log.info("Loading configuration from %s/.zuul.yaml" %
                              (job.project,))
                incdata = self._parseInRepoLayout(job.files['.zuul.yaml'])
                extend_dict(config, incdata)
        return config

    def _parseInRepoLayout(self, data):
        # TODOv3(jeblair): this should implement some rules to protect
        # aspects of the config that should not be changed in-repo
        return yaml.load(data)
