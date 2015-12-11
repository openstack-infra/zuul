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
        project_templates = {}

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

        for project_template in data.get('project-templates', []):
            # Make sure the template only contains valid pipelines
            tpl = dict(
                (pipe_name, project_template.get(pipe_name))
                for pipe_name in layout.pipelines.keys()
                if pipe_name in project_template
            )
            project_templates[project_template.get('name')] = tpl

        for config_job in data.get('jobs', []):
            layout.addJob(JobParser.fromYaml(layout, config_job))

        def add_jobs(job_tree, config_jobs):
            for job in config_jobs:
                if isinstance(job, list):
                    for x in job:
                        add_jobs(job_tree, x)
                if isinstance(job, dict):
                    for parent, children in job.items():
                        parent_tree = job_tree.addJob(layout.getJob(parent))
                        add_jobs(parent_tree, children)
                if isinstance(job, str):
                    job_tree.addJob(layout.getJob(job))

        for config_project in data.get('projects', []):
            shortname = config_project['name'].split('/')[-1]

            # This is reversed due to the prepend operation below, so
            # the ultimate order is templates (in order) followed by
            # statically defined jobs.
            for requested_template in reversed(
                config_project.get('template', [])):
                # Fetch the template from 'project-templates'
                tpl = project_templates.get(
                    requested_template.get('name'))
                # Expand it with the project context
                requested_template['name'] = shortname
                expanded = deep_format(tpl, requested_template)
                # Finally merge the expansion with whatever has been
                # already defined for this project.  Prepend our new
                # jobs to existing ones (which may have been
                # statically defined or defined by other templates).
                for pipeline in layout.pipelines.values():
                    if pipeline.name in expanded:
                        config_project.update(
                            {pipeline.name: expanded[pipeline.name] +
                             config_project.get(pipeline.name, [])})

            mode = config_project.get('merge-mode', 'merge-resolve')
            for pipeline in layout.pipelines.values():
                if pipeline.name in config_project:
                    project = pipeline.source.getProject(
                        config_project['name'])
                    project.merge_mode = model.MERGER_MAP[mode]
                    job_tree = pipeline.addProject(project)
                    config_jobs = config_project[pipeline.name]
                    add_jobs(job_tree, config_jobs)

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

    def _parseSkipIf(self, config_job):
        cm = change_matcher
        skip_matchers = []

        for config_skip in config_job.get('skip-if', []):
            nested_matchers = []

            project_regex = config_skip.get('project')
            if project_regex:
                nested_matchers.append(cm.ProjectMatcher(project_regex))

            branch_regex = config_skip.get('branch')
            if branch_regex:
                nested_matchers.append(cm.BranchMatcher(branch_regex))

            file_regexes = to_list(config_skip.get('all-files-match-any'))
            if file_regexes:
                file_matchers = [cm.FileMatcher(x) for x in file_regexes]
                all_files_matcher = cm.MatchAllFiles(file_matchers)
                nested_matchers.append(all_files_matcher)

            # All patterns need to match a given skip-if predicate
            skip_matchers.append(cm.MatchAll(nested_matchers))

        if skip_matchers:
            # Any skip-if predicate can be matched to trigger a skip
            return cm.MatchAny(skip_matchers)
