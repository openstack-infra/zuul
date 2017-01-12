# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import abc
import copy
import logging
import os
import re
import struct
import time
from uuid import uuid4
import extras

import six

OrderedDict = extras.try_imports(['collections.OrderedDict',
                                  'ordereddict.OrderedDict'])


EMPTY_GIT_REF = '0' * 40  # git sha of all zeros, used during creates/deletes

MERGER_MERGE = 1          # "git merge"
MERGER_MERGE_RESOLVE = 2  # "git merge -s resolve"
MERGER_CHERRY_PICK = 3    # "git cherry-pick"

MERGER_MAP = {
    'merge': MERGER_MERGE,
    'merge-resolve': MERGER_MERGE_RESOLVE,
    'cherry-pick': MERGER_CHERRY_PICK,
}

PRECEDENCE_NORMAL = 0
PRECEDENCE_LOW = 1
PRECEDENCE_HIGH = 2

PRECEDENCE_MAP = {
    None: PRECEDENCE_NORMAL,
    'low': PRECEDENCE_LOW,
    'normal': PRECEDENCE_NORMAL,
    'high': PRECEDENCE_HIGH,
}

# Request states
STATE_REQUESTED = 'requested'
STATE_PENDING = 'pending'
STATE_FULFILLED = 'fulfilled'
STATE_FAILED = 'failed'
REQUEST_STATES = set([STATE_REQUESTED,
                      STATE_PENDING,
                      STATE_FULFILLED,
                      STATE_FAILED])

# Node states
STATE_BUILDING = 'building'
STATE_TESTING = 'testing'
STATE_READY = 'ready'
STATE_IN_USE = 'in-use'
STATE_USED = 'used'
STATE_HOLD = 'hold'
STATE_DELETING = 'deleting'
NODE_STATES = set([STATE_BUILDING,
                   STATE_TESTING,
                   STATE_READY,
                   STATE_IN_USE,
                   STATE_USED,
                   STATE_HOLD,
                   STATE_DELETING])


def time_to_seconds(s):
    if s.endswith('s'):
        return int(s[:-1])
    if s.endswith('m'):
        return int(s[:-1]) * 60
    if s.endswith('h'):
        return int(s[:-1]) * 60 * 60
    if s.endswith('d'):
        return int(s[:-1]) * 24 * 60 * 60
    if s.endswith('w'):
        return int(s[:-1]) * 7 * 24 * 60 * 60
    raise Exception("Unable to parse time value: %s" % s)


def normalizeCategory(name):
    name = name.lower()
    return re.sub(' ', '-', name)


class Attributes(object):
    """A class to hold attributes for string formatting."""

    def __init__(self, **kw):
        setattr(self, '__dict__', kw)


class Pipeline(object):
    """A configuration that ties together triggers, reporters and managers

    Trigger
        A description of which events should be processed

    Manager
        Responsible for enqueing and dequeing Changes

    Reporter
        Communicates success and failure results somewhere
    """
    def __init__(self, name, layout):
        self.name = name
        self.layout = layout
        self.description = None
        self.failure_message = None
        self.merge_failure_message = None
        self.success_message = None
        self.footer_message = None
        self.start_message = None
        self.allow_secrets = False
        self.dequeue_on_new_patchset = True
        self.ignore_dependencies = False
        self.manager = None
        self.queues = []
        self.precedence = PRECEDENCE_NORMAL
        self.triggers = []
        self.start_actions = []
        self.success_actions = []
        self.failure_actions = []
        self.merge_failure_actions = []
        self.disabled_actions = []
        self.disable_at = None
        self._consecutive_failures = 0
        self._disabled = False
        self.window = None
        self.window_floor = None
        self.window_increase_type = None
        self.window_increase_factor = None
        self.window_decrease_type = None
        self.window_decrease_factor = None

    @property
    def actions(self):
        return (
            self.start_actions +
            self.success_actions +
            self.failure_actions +
            self.merge_failure_actions +
            self.disabled_actions
        )

    def __repr__(self):
        return '<Pipeline %s>' % self.name

    def getSafeAttributes(self):
        return Attributes(name=self.name)

    def setManager(self, manager):
        self.manager = manager

    def addQueue(self, queue):
        self.queues.append(queue)

    def getQueue(self, project):
        for queue in self.queues:
            if project in queue.projects:
                return queue
        return None

    def removeQueue(self, queue):
        self.queues.remove(queue)

    def getChangesInQueue(self):
        changes = []
        for shared_queue in self.queues:
            changes.extend([x.change for x in shared_queue.queue])
        return changes

    def getAllItems(self):
        items = []
        for shared_queue in self.queues:
            items.extend(shared_queue.queue)
        return items

    def formatStatusJSON(self):
        j_pipeline = dict(name=self.name,
                          description=self.description)
        j_queues = []
        j_pipeline['change_queues'] = j_queues
        for queue in self.queues:
            j_queue = dict(name=queue.name)
            j_queues.append(j_queue)
            j_queue['heads'] = []
            j_queue['window'] = queue.window

            j_changes = []
            for e in queue.queue:
                if not e.item_ahead:
                    if j_changes:
                        j_queue['heads'].append(j_changes)
                    j_changes = []
                j_changes.append(e.formatJSON())
                if (len(j_changes) > 1 and
                        (j_changes[-2]['remaining_time'] is not None) and
                        (j_changes[-1]['remaining_time'] is not None)):
                    j_changes[-1]['remaining_time'] = max(
                        j_changes[-2]['remaining_time'],
                        j_changes[-1]['remaining_time'])
            if j_changes:
                j_queue['heads'].append(j_changes)
        return j_pipeline


class ChangeQueue(object):
    """A ChangeQueue contains Changes to be processed related projects.

    A Pipeline with a DependentPipelineManager has multiple parallel
    ChangeQueues shared by different projects. For instance, there may a
    ChangeQueue shared by interrelated projects foo and bar, and a second queue
    for independent project baz.

    A Pipeline with an IndependentPipelineManager puts every Change into its
    own ChangeQueue

    The ChangeQueue Window is inspired by TCP windows and controlls how many
    Changes in a given ChangeQueue will be considered active and ready to
    be processed. If a Change succeeds, the Window is increased by
    `window_increase_factor`. If a Change fails, the Window is decreased by
    `window_decrease_factor`.
    """
    def __init__(self, pipeline, window=0, window_floor=1,
                 window_increase_type='linear', window_increase_factor=1,
                 window_decrease_type='exponential', window_decrease_factor=2,
                 name=None):
        self.pipeline = pipeline
        if name:
            self.name = name
        else:
            self.name = ''
        self.projects = []
        self._jobs = set()
        self.queue = []
        self.window = window
        self.window_floor = window_floor
        self.window_increase_type = window_increase_type
        self.window_increase_factor = window_increase_factor
        self.window_decrease_type = window_decrease_type
        self.window_decrease_factor = window_decrease_factor

    def __repr__(self):
        return '<ChangeQueue %s: %s>' % (self.pipeline.name, self.name)

    def getJobs(self):
        return self._jobs

    def addProject(self, project):
        if project not in self.projects:
            self.projects.append(project)

            if not self.name:
                self.name = project.name

    def enqueueChange(self, change):
        item = QueueItem(self, change)
        self.enqueueItem(item)
        item.enqueue_time = time.time()
        return item

    def enqueueItem(self, item):
        item.pipeline = self.pipeline
        item.queue = self
        if self.queue:
            item.item_ahead = self.queue[-1]
            item.item_ahead.items_behind.append(item)
        self.queue.append(item)

    def dequeueItem(self, item):
        if item in self.queue:
            self.queue.remove(item)
        if item.item_ahead:
            item.item_ahead.items_behind.remove(item)
        for item_behind in item.items_behind:
            if item.item_ahead:
                item.item_ahead.items_behind.append(item_behind)
            item_behind.item_ahead = item.item_ahead
        item.item_ahead = None
        item.items_behind = []
        item.dequeue_time = time.time()

    def moveItem(self, item, item_ahead):
        if item.item_ahead == item_ahead:
            return False
        # Remove from current location
        if item.item_ahead:
            item.item_ahead.items_behind.remove(item)
        for item_behind in item.items_behind:
            if item.item_ahead:
                item.item_ahead.items_behind.append(item_behind)
            item_behind.item_ahead = item.item_ahead
        # Add to new location
        item.item_ahead = item_ahead
        item.items_behind = []
        if item.item_ahead:
            item.item_ahead.items_behind.append(item)
        return True

    def isActionable(self, item):
        if self.window:
            return item in self.queue[:self.window]
        else:
            return True

    def increaseWindowSize(self):
        if self.window:
            if self.window_increase_type == 'linear':
                self.window += self.window_increase_factor
            elif self.window_increase_type == 'exponential':
                self.window *= self.window_increase_factor

    def decreaseWindowSize(self):
        if self.window:
            if self.window_decrease_type == 'linear':
                self.window = max(
                    self.window_floor,
                    self.window - self.window_decrease_factor)
            elif self.window_decrease_type == 'exponential':
                self.window = max(
                    self.window_floor,
                    int(self.window / self.window_decrease_factor))


class Project(object):
    """A Project represents a git repository such as openstack/nova."""

    # NOTE: Projects should only be instantiated via a Source object
    # so that they are associated with and cached by their Connection.
    # This makes a Project instance a unique identifier for a given
    # project from a given source.

    def __init__(self, name, source, foreign=False):
        self.name = name
        self.source = source
        self.connection_name = source.connection.connection_name
        self.canonical_hostname = source.canonical_hostname
        self.canonical_name = source.canonical_hostname + '/' + name
        # foreign projects are those referenced in dependencies
        # of layout projects, this should matter
        # when deciding whether to enqueue their changes
        # TODOv3 (jeblair): re-add support for foreign projects if needed
        self.foreign = foreign
        self.unparsed_config = None
        self.unparsed_branch_config = {}  # branch -> UnparsedTenantConfig

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Project %s>' % (self.name)


class Node(object):
    """A single node for use by a job.

    This may represent a request for a node, or an actual node
    provided by Nodepool.
    """

    def __init__(self, name, image):
        self.name = name
        self.image = image
        self.id = None
        self.lock = None
        # Attributes from Nodepool
        self._state = 'unknown'
        self.state_time = time.time()
        self.interface_ip = None
        self.public_ipv4 = None
        self.private_ipv4 = None
        self.public_ipv6 = None
        self._keys = []
        self.az = None
        self.provider = None
        self.region = None

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if value not in NODE_STATES:
            raise TypeError("'%s' is not a valid state" % value)
        self._state = value
        self.state_time = time.time()

    def __repr__(self):
        return '<Node %s %s:%s>' % (self.id, self.name, self.image)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, Node):
            return False
        return (self.name == other.name and
                self.image == other.image and
                self.id == other.id)

    def toDict(self):
        d = {}
        d['state'] = self.state
        for k in self._keys:
            d[k] = getattr(self, k)
        return d

    def updateFromDict(self, data):
        self._state = data['state']
        keys = []
        for k, v in data.items():
            if k == 'state':
                continue
            keys.append(k)
            setattr(self, k, v)
        self._keys = keys


class NodeSet(object):
    """A set of nodes.

    In configuration, NodeSets are attributes of Jobs indicating that
    a Job requires nodes matching this description.

    They may appear as top-level configuration objects and be named,
    or they may appears anonymously in in-line job definitions.
    """

    def __init__(self, name=None):
        self.name = name or ''
        self.nodes = OrderedDict()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, NodeSet):
            return False
        return (self.name == other.name and
                self.nodes == other.nodes)

    def copy(self):
        n = NodeSet(self.name)
        for name, node in self.nodes.items():
            n.addNode(Node(node.name, node.image))
        return n

    def addNode(self, node):
        if node.name in self.nodes:
            raise Exception("Duplicate node in %s" % (self,))
        self.nodes[node.name] = node

    def getNodes(self):
        return self.nodes.values()

    def __repr__(self):
        if self.name:
            name = self.name + ' '
        else:
            name = ''
        return '<NodeSet %s%s>' % (name, self.nodes)


class NodeRequest(object):
    """A request for a set of nodes."""

    def __init__(self, requestor, build_set, job, nodeset):
        self.requestor = requestor
        self.build_set = build_set
        self.job = job
        self.nodeset = nodeset
        self._state = STATE_REQUESTED
        self.state_time = time.time()
        self.stat = None
        self.uid = uuid4().hex
        self.id = None
        # Zuul internal failure flag (not stored in ZK so it's not
        # overwritten).
        self.failed = False

    @property
    def fulfilled(self):
        return (self._state == STATE_FULFILLED) and not self.failed

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if value not in REQUEST_STATES:
            raise TypeError("'%s' is not a valid state" % value)
        self._state = value
        self.state_time = time.time()

    def __repr__(self):
        return '<NodeRequest %s %s>' % (self.id, self.nodeset)

    def toDict(self):
        d = {}
        nodes = [n.image for n in self.nodeset.getNodes()]
        d['node_types'] = nodes
        d['requestor'] = self.requestor
        d['state'] = self.state
        d['state_time'] = self.state_time
        return d

    def updateFromDict(self, data):
        self._state = data['state']
        self.state_time = data['state_time']


class Secret(object):
    """A collection of private data.

    In configuration, Secrets are collections of private data in
    key-value pair format.  They are defined as top-level
    configuration objects and then referenced by Jobs.

    """

    def __init__(self, name, source_context):
        self.name = name
        self.source_context = source_context
        # The secret data may or may not be encrypted.  This attribute
        # is named 'secret_data' to make it easy to search for and
        # spot where it is directly used.
        self.secret_data = {}

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, Secret):
            return False
        return (self.name == other.name and
                self.source_context == other.source_context and
                self.secret_data == other.secret_data)

    def __repr__(self):
        return '<Secret %s>' % (self.name,)

    def decrypt(self, private_key):
        """Return a copy of this secret with any encrypted data decrypted.
        Note that the original remains encrypted."""

        r = copy.deepcopy(self)
        decrypted_secret_data = {}
        for k, v in r.secret_data.items():
            if hasattr(v, 'decrypt'):
                decrypted_secret_data[k] = v.decrypt(private_key)
            else:
                decrypted_secret_data[k] = v
        r.secret_data = decrypted_secret_data
        return r


class SourceContext(object):
    """A reference to the branch of a project in configuration.

    Jobs and playbooks reference this to keep track of where they
    originate."""

    def __init__(self, project, branch, path, trusted):
        self.project = project
        self.branch = branch
        self.path = path
        self.trusted = trusted

    def __str__(self):
        return '%s/%s@%s' % (self.project, self.path, self.branch)

    def __repr__(self):
        return '<SourceContext %s trusted:%s>' % (str(self),
                                                  self.trusted)

    def __deepcopy__(self, memo):
        return self.copy()

    def copy(self):
        return self.__class__(self.project, self.branch, self.path,
                              self.trusted)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, SourceContext):
            return False
        return (self.project == other.project and
                self.branch == other.branch and
                self.path == other.path and
                self.trusted == other.trusted)


class PlaybookContext(object):

    """A reference to a playbook in the context of a project.

    Jobs refer to objects of this class for their main, pre, and post
    playbooks so that we can keep track of which repos and security
    contexts are needed in order to run them."""

    def __init__(self, source_context, path):
        self.source_context = source_context
        self.path = path

    def __repr__(self):
        return '<PlaybookContext %s %s>' % (self.source_context,
                                            self.path)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, PlaybookContext):
            return False
        return (self.source_context == other.source_context and
                self.path == other.path)

    def toDict(self):
        # Render to a dict to use in passing json to the executor
        return dict(
            connection=self.source_context.project.connection_name,
            project=self.source_context.project.name,
            branch=self.source_context.branch,
            trusted=self.source_context.trusted,
            path=self.path)


@six.add_metaclass(abc.ABCMeta)
class Role(object):
    """A reference to an ansible role."""

    def __init__(self, target_name):
        self.target_name = target_name

    @abc.abstractmethod
    def __repr__(self):
        pass

    def __ne__(self, other):
        return not self.__eq__(other)

    @abc.abstractmethod
    def __eq__(self, other):
        if not isinstance(other, Role):
            return False
        return (self.target_name == other.target_name)

    @abc.abstractmethod
    def toDict(self):
        # Render to a dict to use in passing json to the executor
        return dict(target_name=self.target_name)


class ZuulRole(Role):
    """A reference to an ansible role in a Zuul project."""

    def __init__(self, target_name, connection_name, project_name, trusted):
        super(ZuulRole, self).__init__(target_name)
        self.connection_name = connection_name
        self.project_name = project_name
        self.trusted = trusted

    def __repr__(self):
        return '<ZuulRole %s %s>' % (self.project_name, self.target_name)

    def __eq__(self, other):
        if not isinstance(other, ZuulRole):
            return False
        return (super(ZuulRole, self).__eq__(other) and
                self.connection_name == other.connection_name,
                self.project_name == other.project_name,
                self.trusted == other.trusted)

    def toDict(self):
        # Render to a dict to use in passing json to the executor
        d = super(ZuulRole, self).toDict()
        d['type'] = 'zuul'
        d['connection'] = self.connection_name
        d['project'] = self.project_name
        d['trusted'] = self.trusted
        return d


class AuthContext(object):
    """The authentication information for a job.

    Authentication information (both the actual data and metadata such
    as whether it should be inherited) for a job is grouped together
    in this object.
    """

    def __init__(self, inherit=False):
        self.inherit = inherit
        self.secrets = []

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        if not isinstance(other, AuthContext):
            return False
        return (self.inherit == other.inherit and
                self.secrets == other.secrets)


class Job(object):

    """A Job represents the defintion of actions to perform.

    A Job is an abstract configuration concept.  It describes what,
    where, and under what circumstances something should be run
    (contrast this with Build which is a concrete single execution of
    a Job).

    NB: Do not modify attributes of this class, set them directly
    (e.g., "job.run = ..." rather than "job.run.append(...)").
    """

    def __init__(self, name):
        # These attributes may override even the final form of a job
        # in the context of a project-pipeline.  They can not affect
        # the execution of the job, but only whether the job is run
        # and how it is reported.
        self.context_attributes = dict(
            voting=True,
            hold_following_changes=False,
            failure_message=None,
            success_message=None,
            failure_url=None,
            success_url=None,
            # Matchers.  These are separate so they can be individually
            # overidden.
            branch_matcher=None,
            file_matcher=None,
            irrelevant_file_matcher=None,  # skip-if
            tags=frozenset(),
            dependencies=frozenset(),
        )

        # These attributes affect how the job is actually run and more
        # care must be taken when overriding them.  If a job is
        # declared "final", these may not be overriden in a
        # project-pipeline.
        self.execution_attributes = dict(
            timeout=None,
            variables={},
            nodeset=NodeSet(),
            auth=None,
            workspace=None,
            pre_run=(),
            post_run=(),
            run=(),
            implied_run=(),
            semaphore=None,
            attempts=3,
            final=False,
            roles=frozenset(),
            repos=frozenset(),
            allowed_projects=None,
        )

        # These are generally internal attributes which are not
        # accessible via configuration.
        self.other_attributes = dict(
            name=None,
            source_context=None,
            inheritance_path=(),
        )

        self.inheritable_attributes = {}
        self.inheritable_attributes.update(self.context_attributes)
        self.inheritable_attributes.update(self.execution_attributes)
        self.attributes = {}
        self.attributes.update(self.inheritable_attributes)
        self.attributes.update(self.other_attributes)

        self.name = name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        # Compare the name and all inheritable attributes to determine
        # whether two jobs with the same name are identically
        # configured.  Useful upon reconfiguration.
        if not isinstance(other, Job):
            return False
        if self.name != other.name:
            return False
        for k, v in self.attributes.items():
            if getattr(self, k) != getattr(other, k):
                return False
        return True

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<Job %s branches: %s source: %s>' % (self.name,
                                                     self.branch_matcher,
                                                     self.source_context)

    def __getattr__(self, name):
        v = self.__dict__.get(name)
        if v is None:
            return copy.deepcopy(self.attributes[name])
        return v

    def _get(self, name):
        return self.__dict__.get(name)

    def getSafeAttributes(self):
        return Attributes(name=self.name)

    def setRun(self):
        if not self.run:
            self.run = self.implied_run

    def updateVariables(self, other_vars):
        v = self.variables
        Job._deepUpdate(v, other_vars)
        self.variables = v

    @staticmethod
    def _deepUpdate(a, b):
        # Merge nested dictionaries if possible, otherwise, overwrite
        # the value in 'a' with the value in 'b'.
        for k, bv in b.items():
            av = a.get(k)
            if isinstance(av, dict) and isinstance(bv, dict):
                Job._deepUpdate(av, bv)
            else:
                a[k] = bv

    def inheritFrom(self, other):
        """Copy the inheritable attributes which have been set on the other
        job to this job."""
        if not isinstance(other, Job):
            raise Exception("Job unable to inherit from %s" % (other,))

        do_not_inherit = set()
        if other.auth and not other.auth.inherit:
            do_not_inherit.add('auth')

        # copy all attributes
        for k in self.inheritable_attributes:
            if (other._get(k) is not None and k not in do_not_inherit):
                setattr(self, k, copy.deepcopy(getattr(other, k)))

        msg = 'inherit from %s' % (repr(other),)
        self.inheritance_path = other.inheritance_path + (msg,)

    def copy(self):
        job = Job(self.name)
        for k in self.attributes:
            if self._get(k) is not None:
                setattr(job, k, copy.deepcopy(self._get(k)))
        return job

    def applyVariant(self, other):
        """Copy the attributes which have been set on the other job to this
        job."""

        if not isinstance(other, Job):
            raise Exception("Job unable to inherit from %s" % (other,))

        for k in self.execution_attributes:
            if (other._get(k) is not None and
                k not in set(['final'])):
                if self.final:
                    raise Exception("Unable to modify final job %s attribute "
                                    "%s=%s with variant %s" % (
                                        repr(self), k, other._get(k),
                                        repr(other)))
                if k not in set(['pre_run', 'post_run', 'roles', 'variables']):
                    setattr(self, k, copy.deepcopy(other._get(k)))

        # Don't set final above so that we don't trip an error halfway
        # through assignment.
        if other.final != self.attributes['final']:
            self.final = other.final

        if other._get('pre_run') is not None:
            self.pre_run = self.pre_run + other.pre_run
        if other._get('post_run') is not None:
            self.post_run = other.post_run + self.post_run
        if other._get('roles') is not None:
            self.roles = self.roles.union(other.roles)
        if other._get('variables') is not None:
            self.updateVariables(other.variables)

        for k in self.context_attributes:
            if (other._get(k) is not None and
                k not in set(['tags'])):
                setattr(self, k, copy.deepcopy(other._get(k)))

        if other._get('tags') is not None:
            self.tags = self.tags.union(other.tags)

        msg = 'apply variant %s' % (repr(other),)
        self.inheritance_path = self.inheritance_path + (msg,)

    def changeMatches(self, change):
        if self.branch_matcher and not self.branch_matcher.matches(change):
            return False

        if self.file_matcher and not self.file_matcher.matches(change):
            return False

        # NB: This is a negative match.
        if (self.irrelevant_file_matcher and
            self.irrelevant_file_matcher.matches(change)):
            return False

        return True


class JobList(object):
    """ A list of jobs in a project's pipeline. """

    def __init__(self):
        self.jobs = OrderedDict()  # job.name -> [job, ...]

    def addJob(self, job):
        if job.name in self.jobs:
            self.jobs[job.name].append(job)
        else:
            self.jobs[job.name] = [job]

    def inheritFrom(self, other):
        for jobname, jobs in other.jobs.items():
            if jobname in self.jobs:
                self.jobs[jobname].append(jobs)
            else:
                self.jobs[jobname] = jobs


class JobGraph(object):
    """ A JobGraph represents the dependency graph between Job."""

    def __init__(self):
        self.jobs = OrderedDict()  # job_name -> Job
        self._dependencies = {}  # dependent_job_name -> set(parent_job_names)

    def __repr__(self):
        return '<JobGraph %s>' % (self.jobs)

    def addJob(self, job):
        # A graph must be created after the job list is frozen,
        # therefore we should only get one job with the same name.
        if job.name in self.jobs:
            raise Exception("Job %s already added" % (job.name,))
        self.jobs[job.name] = job
        # Append the dependency information
        self._dependencies.setdefault(job.name, set())
        try:
            for dependency in job.dependencies:
                # Make sure a circular dependency is never created
                ancestor_jobs = self._getParentJobNamesRecursively(
                    dependency, soft=True)
                ancestor_jobs.add(dependency)
                if any((job.name == anc_job) for anc_job in ancestor_jobs):
                    raise Exception("Dependency cycle detected in job %s" %
                                    (job.name,))
                self._dependencies[job.name].add(dependency)
        except Exception:
            del self.jobs[job.name]
            del self._dependencies[job.name]
            raise

    def getJobs(self):
        return self.jobs.values()  # Report in the order of the layout config

    def _getDirectDependentJobs(self, parent_job):
        ret = set()
        for dependent_name, parent_names in self._dependencies.items():
            if parent_job in parent_names:
                ret.add(dependent_name)
        return ret

    def getDependentJobsRecursively(self, parent_job):
        all_dependent_jobs = set()
        jobs_to_iterate = set([parent_job])
        while len(jobs_to_iterate) > 0:
            current_job = jobs_to_iterate.pop()
            current_dependent_jobs = self._getDirectDependentJobs(current_job)
            new_dependent_jobs = current_dependent_jobs - all_dependent_jobs
            jobs_to_iterate |= new_dependent_jobs
            all_dependent_jobs |= new_dependent_jobs
        return [self.jobs[name] for name in all_dependent_jobs]

    def getParentJobsRecursively(self, dependent_job):
        return [self.jobs[name] for name in
                self._getParentJobNamesRecursively(dependent_job)]

    def _getParentJobNamesRecursively(self, dependent_job, soft=False):
        all_parent_jobs = set()
        jobs_to_iterate = set([dependent_job])
        while len(jobs_to_iterate) > 0:
            current_job = jobs_to_iterate.pop()
            current_parent_jobs = self._dependencies.get(current_job)
            if current_parent_jobs is None:
                if soft:
                    current_parent_jobs = set()
                else:
                    raise Exception("Dependent job %s not found: " %
                                    (dependent_job,))
            new_parent_jobs = current_parent_jobs - all_parent_jobs
            jobs_to_iterate |= new_parent_jobs
            all_parent_jobs |= new_parent_jobs
        return all_parent_jobs


class Build(object):
    """A Build is an instance of a single execution of a Job.

    While a Job describes what to run, a Build describes an actual
    execution of that Job.  Each build is associated with exactly one
    Job (related builds are grouped together in a BuildSet).
    """

    def __init__(self, job, uuid):
        self.job = job
        self.uuid = uuid
        self.url = None
        self.result = None
        self.build_set = None
        self.execute_time = time.time()
        self.start_time = None
        self.end_time = None
        self.estimated_time = None
        self.pipeline = None
        self.canceled = False
        self.retry = False
        self.parameters = {}
        self.worker = Worker()
        self.node_labels = []
        self.node_name = None

    def __repr__(self):
        return ('<Build %s of %s on %s>' %
                (self.uuid, self.job.name, self.worker))

    def getSafeAttributes(self):
        return Attributes(uuid=self.uuid)


class Worker(object):
    """Information about the specific worker executing a Build."""
    def __init__(self):
        self.name = "Unknown"
        self.hostname = None
        self.ips = []
        self.fqdn = None
        self.program = None
        self.version = None
        self.extra = {}

    def updateFromData(self, data):
        """Update worker information if contained in the WORK_DATA response."""
        self.name = data.get('worker_name', self.name)
        self.hostname = data.get('worker_hostname', self.hostname)
        self.ips = data.get('worker_ips', self.ips)
        self.fqdn = data.get('worker_fqdn', self.fqdn)
        self.program = data.get('worker_program', self.program)
        self.version = data.get('worker_version', self.version)
        self.extra = data.get('worker_extra', self.extra)

    def __repr__(self):
        return '<Worker %s>' % self.name


class RepoFiles(object):
    """RepoFiles holds config-file content for per-project job config.

    When Zuul asks a merger to prepare a future multiple-repo state
    and collect Zuul configuration files so that we can dynamically
    load our configuration, this class provides cached access to that
    data for use by the Change which updated the config files and any
    changes that follow it in a ChangeQueue.

    It is attached to a BuildSet since the content of Zuul
    configuration files can change with each new BuildSet.
    """

    def __init__(self):
        self.connections = {}

    def __repr__(self):
        return '<RepoFiles %s>' % self.connections

    def setFiles(self, items):
        self.hostnames = {}
        for item in items:
            connection = self.connections.setdefault(
                item['connection'], {})
            project = connection.setdefault(item['project'], {})
            branch = project.setdefault(item['branch'], {})
            branch.update(item['files'])

    def getFile(self, connection_name, project_name, branch, fn):
        host = self.connections.get(connection_name, {})
        return host.get(project_name, {}).get(branch, {}).get(fn)


class BuildSet(object):
    """A collection of Builds for one specific potential future repository
    state.

    When Zuul executes Builds for a change, it creates a Build to
    represent each execution of each job and a BuildSet to keep track
    of all the Builds running for that Change.  When Zuul re-executes
    Builds for a Change with a different configuration, all of the
    running Builds in the BuildSet for that change are aborted, and a
    new BuildSet is created to hold the Builds for the Jobs being
    run with the new configuration.

    A BuildSet also holds the UUID used to produce the Zuul Ref that
    builders check out.

    """
    # Merge states:
    NEW = 1
    PENDING = 2
    COMPLETE = 3

    states_map = {
        1: 'NEW',
        2: 'PENDING',
        3: 'COMPLETE',
    }

    def __init__(self, item):
        self.item = item
        self.other_changes = []
        self.builds = {}
        self.result = None
        self.next_build_set = None
        self.previous_build_set = None
        self.ref = None
        self.commit = None
        self.zuul_url = None
        self.unable_to_merge = False
        self.config_error = None  # None or an error message string.
        self.failing_reasons = []
        self.merge_state = self.NEW
        self.nodesets = {}  # job -> nodeset
        self.node_requests = {}  # job -> reqs
        self.files = RepoFiles()
        self.layout = None
        self.tries = {}

    def __repr__(self):
        return '<BuildSet item: %s #builds: %s merge state: %s>' % (
            self.item,
            len(self.builds),
            self.getStateName(self.merge_state))

    def setConfiguration(self):
        # The change isn't enqueued until after it's created
        # so we don't know what the other changes ahead will be
        # until jobs start.
        if not self.other_changes:
            next_item = self.item.item_ahead
            while next_item:
                self.other_changes.append(next_item.change)
                next_item = next_item.item_ahead
        if not self.ref:
            self.ref = 'Z' + uuid4().hex

    def getStateName(self, state_num):
        return self.states_map.get(
            state_num, 'UNKNOWN (%s)' % state_num)

    def addBuild(self, build):
        self.builds[build.job.name] = build
        if build.job.name not in self.tries:
            self.tries[build.job.name] = 1
        build.build_set = self

    def removeBuild(self, build):
        self.tries[build.job.name] += 1
        del self.builds[build.job.name]

    def getBuild(self, job_name):
        return self.builds.get(job_name)

    def getBuilds(self):
        keys = self.builds.keys()
        keys.sort()
        return [self.builds.get(x) for x in keys]

    def getJobNodeSet(self, job_name):
        # Return None if not provisioned; empty NodeSet if no nodes
        # required
        return self.nodesets.get(job_name)

    def removeJobNodeSet(self, job_name):
        if job_name not in self.nodesets:
            raise Exception("No job set for %s" % (job_name))
        del self.nodesets[job_name]

    def setJobNodeRequest(self, job_name, req):
        if job_name in self.node_requests:
            raise Exception("Prior node request for %s" % (job_name))
        self.node_requests[job_name] = req

    def getJobNodeRequest(self, job_name):
        return self.node_requests.get(job_name)

    def jobNodeRequestComplete(self, job_name, req, nodeset):
        if job_name in self.nodesets:
            raise Exception("Prior node request for %s" % (job_name))
        self.nodesets[job_name] = nodeset
        del self.node_requests[job_name]

    def getTries(self, job_name):
        return self.tries.get(job_name)

    def getMergeMode(self):
        if self.layout:
            project = self.item.change.project
            project_config = self.layout.project_configs.get(
                project.canonical_name)
            if project_config:
                return project_config.merge_mode
        return MERGER_MERGE_RESOLVE


class QueueItem(object):
    """Represents the position of a Change in a ChangeQueue.

    All Changes are enqueued into ChangeQueue in a QueueItem. The QueueItem
    holds the current `BuildSet` as well as all previous `BuildSets` that were
    produced for this `QueueItem`.
    """
    log = logging.getLogger("zuul.QueueItem")

    def __init__(self, queue, change):
        self.pipeline = queue.pipeline
        self.queue = queue
        self.change = change  # a changeish
        self.build_sets = []
        self.dequeued_needing_change = False
        self.current_build_set = BuildSet(self)
        self.build_sets.append(self.current_build_set)
        self.item_ahead = None
        self.items_behind = []
        self.enqueue_time = None
        self.dequeue_time = None
        self.reported = False
        self.active = False  # Whether an item is within an active window
        self.live = True  # Whether an item is intended to be processed at all
        self.layout = None  # This item's shadow layout
        self.job_graph = None

    def __repr__(self):
        if self.pipeline:
            pipeline = self.pipeline.name
        else:
            pipeline = None
        return '<QueueItem 0x%x for %s in %s>' % (
            id(self), self.change, pipeline)

    def resetAllBuilds(self):
        old = self.current_build_set
        self.current_build_set.result = 'CANCELED'
        self.current_build_set = BuildSet(self)
        old.next_build_set = self.current_build_set
        self.current_build_set.previous_build_set = old
        self.build_sets.append(self.current_build_set)

    def addBuild(self, build):
        self.current_build_set.addBuild(build)
        build.pipeline = self.pipeline

    def removeBuild(self, build):
        self.current_build_set.removeBuild(build)

    def setReportedResult(self, result):
        self.current_build_set.result = result

    def freezeJobGraph(self):
        """Find or create actual matching jobs for this item's change and
        store the resulting job tree."""
        layout = self.current_build_set.layout
        job_graph = layout.createJobGraph(self)
        for job in job_graph.getJobs():
            # Ensure that each jobs's dependencies are fully
            # accessible.  This will raise an exception if not.
            job_graph.getParentJobsRecursively(job.name)
        self.job_graph = job_graph

    def hasJobGraph(self):
        """Returns True if the item has a job graph."""
        return self.job_graph is not None

    def getJobs(self):
        if not self.live or not self.job_graph:
            return []
        return self.job_graph.getJobs()

    def getJob(self, name):
        if not self.job_graph:
            return None
        return self.job_graph.jobs.get(name)

    def haveAllJobsStarted(self):
        if not self.hasJobGraph():
            return False
        for job in self.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if not build or not build.start_time:
                return False
        return True

    def areAllJobsComplete(self):
        if (self.current_build_set.config_error or
            self.current_build_set.unable_to_merge):
            return True
        if not self.hasJobGraph():
            return False
        for job in self.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if not build or not build.result:
                return False
        return True

    def didAllJobsSucceed(self):
        if not self.hasJobGraph():
            return False
        for job in self.getJobs():
            if not job.voting:
                continue
            build = self.current_build_set.getBuild(job.name)
            if not build:
                return False
            if build.result != 'SUCCESS':
                return False
        return True

    def didAnyJobFail(self):
        if not self.hasJobGraph():
            return False
        for job in self.getJobs():
            if not job.voting:
                continue
            build = self.current_build_set.getBuild(job.name)
            if build and build.result and (build.result != 'SUCCESS'):
                return True
        return False

    def didMergerFail(self):
        return self.current_build_set.unable_to_merge

    def getConfigError(self):
        return self.current_build_set.config_error

    def isHoldingFollowingChanges(self):
        if not self.live:
            return False
        if not self.hasJobGraph():
            return False
        for job in self.getJobs():
            if not job.hold_following_changes:
                continue
            build = self.current_build_set.getBuild(job.name)
            if not build:
                return True
            if build.result != 'SUCCESS':
                return True

        if not self.item_ahead:
            return False
        return self.item_ahead.isHoldingFollowingChanges()

    def findJobsToRun(self, semaphore_handler):
        torun = []
        if not self.live:
            return []
        if not self.job_graph:
            return []
        if self.item_ahead:
            # Only run jobs if any 'hold' jobs on the change ahead
            # have completed successfully.
            if self.item_ahead.isHoldingFollowingChanges():
                return []

        successful_job_names = set()
        jobs_not_started = set()
        for job in self.job_graph.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if build:
                if build.result == 'SUCCESS':
                    successful_job_names.add(job.name)
            else:
                jobs_not_started.add(job)

        # Attempt to request nodes for jobs in the order jobs appear
        # in configuration.
        for job in self.job_graph.getJobs():
            if job not in jobs_not_started:
                continue
            all_parent_jobs_successful = True
            for parent_job in self.job_graph.getParentJobsRecursively(
                    job.name):
                if parent_job.name not in successful_job_names:
                    all_parent_jobs_successful = False
                    break
            if all_parent_jobs_successful:
                nodeset = self.current_build_set.getJobNodeSet(job.name)
                if nodeset is None:
                    # The nodes for this job are not ready, skip
                    # it for now.
                    continue
                if semaphore_handler.acquire(self, job):
                    # If this job needs a semaphore, either acquire it or
                    # make sure that we have it before running the job.
                    torun.append(job)
        return torun

    def findJobsToRequest(self):
        build_set = self.current_build_set
        toreq = []
        if not self.live:
            return []
        if not self.job_graph:
            return []
        if self.item_ahead:
            if self.item_ahead.isHoldingFollowingChanges():
                return []

        successful_job_names = set()
        jobs_not_requested = set()
        for job in self.job_graph.getJobs():
            build = build_set.getBuild(job.name)
            if build and build.result == 'SUCCESS':
                successful_job_names.add(job.name)
            else:
                nodeset = build_set.getJobNodeSet(job.name)
                if nodeset is None:
                    req = build_set.getJobNodeRequest(job.name)
                    if req is None:
                        jobs_not_requested.add(job)

        # Attempt to request nodes for jobs in the order jobs appear
        # in configuration.
        for job in self.job_graph.getJobs():
            if job not in jobs_not_requested:
                continue
            all_parent_jobs_successful = True
            for parent_job in self.job_graph.getParentJobsRecursively(
                    job.name):
                if parent_job.name not in successful_job_names:
                    all_parent_jobs_successful = False
                    break
            if all_parent_jobs_successful:
                toreq.append(job)
        return toreq

    def setResult(self, build):
        if build.retry:
            self.removeBuild(build)
        elif build.result != 'SUCCESS':
            for job in self.job_graph.getDependentJobsRecursively(
                    build.job.name):
                fakebuild = Build(job, None)
                fakebuild.result = 'SKIPPED'
                self.addBuild(fakebuild)

    def setNodeRequestFailure(self, job):
        fakebuild = Build(job, None)
        self.addBuild(fakebuild)
        fakebuild.result = 'NODE_FAILURE'
        self.setResult(fakebuild)

    def setDequeuedNeedingChange(self):
        self.dequeued_needing_change = True
        self._setAllJobsSkipped()

    def setUnableToMerge(self):
        self.current_build_set.unable_to_merge = True
        self._setAllJobsSkipped()

    def setConfigError(self, error):
        self.current_build_set.config_error = error
        self._setAllJobsSkipped()

    def _setAllJobsSkipped(self):
        for job in self.getJobs():
            fakebuild = Build(job, None)
            fakebuild.result = 'SKIPPED'
            self.addBuild(fakebuild)

    def formatUrlPattern(self, url_pattern, job=None, build=None):
        url = None
        # Produce safe versions of objects which may be useful in
        # result formatting, but don't allow users to crawl through
        # the entire data structure where they might be able to access
        # secrets, etc.
        safe_change = self.change.getSafeAttributes()
        safe_pipeline = self.pipeline.getSafeAttributes()
        safe_job = job.getSafeAttributes()
        safe_build = build.getSafeAttributes()
        try:
            url = url_pattern.format(change=safe_change,
                                     pipeline=safe_pipeline,
                                     job=safe_job,
                                     build=safe_build)
        except KeyError as e:
            self.log.error("Error while formatting url for job %s: unknown "
                           "key %s in pattern %s"
                           % (job, e.message, url_pattern))
        except AttributeError as e:
            self.log.error("Error while formatting url for job %s: unknown "
                           "attribute %s in pattern %s"
                           % (job, e.message, url_pattern))
        except Exception:
            self.log.exception("Error while formatting url for job %s with "
                               "pattern %s:" % (job, url_pattern))

        return url

    def formatJobResult(self, job):
        build = self.current_build_set.getBuild(job.name)
        result = build.result
        pattern = None
        if result == 'SUCCESS':
            if job.success_message:
                result = job.success_message
            if job.success_url:
                pattern = job.success_url
        elif result == 'FAILURE':
            if job.failure_message:
                result = job.failure_message
            if job.failure_url:
                pattern = job.failure_url
        url = None
        if pattern:
            url = self.formatUrlPattern(pattern, job, build)
        if not url:
            url = build.url or job.name
        return (result, url)

    def formatJSON(self):
        changeish = self.change
        ret = {}
        ret['active'] = self.active
        ret['live'] = self.live
        if hasattr(changeish, 'url') and changeish.url is not None:
            ret['url'] = changeish.url
        else:
            ret['url'] = None
        ret['id'] = changeish._id()
        if self.item_ahead:
            ret['item_ahead'] = self.item_ahead.change._id()
        else:
            ret['item_ahead'] = None
        ret['items_behind'] = [i.change._id() for i in self.items_behind]
        ret['failing_reasons'] = self.current_build_set.failing_reasons
        ret['zuul_ref'] = self.current_build_set.ref
        if changeish.project:
            ret['project'] = changeish.project.name
        else:
            # For cross-project dependencies with the depends-on
            # project not known to zuul, the project is None
            # Set it to a static value
            ret['project'] = "Unknown Project"
        ret['enqueue_time'] = int(self.enqueue_time * 1000)
        ret['jobs'] = []
        if hasattr(changeish, 'owner'):
            ret['owner'] = changeish.owner
        else:
            ret['owner'] = None
        max_remaining = 0
        for job in self.getJobs():
            now = time.time()
            build = self.current_build_set.getBuild(job.name)
            elapsed = None
            remaining = None
            result = None
            build_url = None
            report_url = None
            worker = None
            if build:
                result = build.result
                build_url = build.url
                (unused, report_url) = self.formatJobResult(job)
                if build.start_time:
                    if build.end_time:
                        elapsed = int((build.end_time -
                                       build.start_time) * 1000)
                        remaining = 0
                    else:
                        elapsed = int((now - build.start_time) * 1000)
                        if build.estimated_time:
                            remaining = max(
                                int(build.estimated_time * 1000) - elapsed,
                                0)
                worker = {
                    'name': build.worker.name,
                    'hostname': build.worker.hostname,
                    'ips': build.worker.ips,
                    'fqdn': build.worker.fqdn,
                    'program': build.worker.program,
                    'version': build.worker.version,
                    'extra': build.worker.extra
                }
            if remaining and remaining > max_remaining:
                max_remaining = remaining

            ret['jobs'].append({
                'name': job.name,
                'elapsed_time': elapsed,
                'remaining_time': remaining,
                'url': build_url,
                'report_url': report_url,
                'result': result,
                'voting': job.voting,
                'uuid': build.uuid if build else None,
                'execute_time': build.execute_time if build else None,
                'start_time': build.start_time if build else None,
                'end_time': build.end_time if build else None,
                'estimated_time': build.estimated_time if build else None,
                'pipeline': build.pipeline.name if build else None,
                'canceled': build.canceled if build else None,
                'retry': build.retry if build else None,
                'node_labels': build.node_labels if build else [],
                'node_name': build.node_name if build else None,
                'worker': worker,
            })

        if self.haveAllJobsStarted():
            ret['remaining_time'] = max_remaining
        else:
            ret['remaining_time'] = None
        return ret

    def formatStatus(self, indent=0, html=False):
        changeish = self.change
        indent_str = ' ' * indent
        ret = ''
        if html and hasattr(changeish, 'url') and changeish.url is not None:
            ret += '%sProject %s change <a href="%s">%s</a>\n' % (
                indent_str,
                changeish.project.name,
                changeish.url,
                changeish._id())
        else:
            ret += '%sProject %s change %s based on %s\n' % (
                indent_str,
                changeish.project.name,
                changeish._id(),
                self.item_ahead)
        for job in self.getJobs():
            build = self.current_build_set.getBuild(job.name)
            if build:
                result = build.result
            else:
                result = None
            job_name = job.name
            if not job.voting:
                voting = ' (non-voting)'
            else:
                voting = ''
            if html:
                if build:
                    url = build.url
                else:
                    url = None
                if url is not None:
                    job_name = '<a href="%s">%s</a>' % (url, job_name)
            ret += '%s  %s: %s%s' % (indent_str, job_name, result, voting)
            ret += '\n'
        return ret

    def makeMergerItem(self):
        # Create a dictionary with all info about the item needed by
        # the merger.
        number = None
        patchset = None
        oldrev = None
        newrev = None
        refspec = None
        if hasattr(self.change, 'number'):
            number = self.change.number
            patchset = self.change.patchset
            refspec = self.change.refspec
            branch = self.change.branch
        elif hasattr(self.change, 'newrev'):
            oldrev = self.change.oldrev
            newrev = self.change.newrev
            branch = self.change.ref
        else:
            oldrev = None
            newrev = None
            branch = None
        source = self.change.project.source
        connection_name = source.connection.connection_name
        project = self.change.project

        return dict(project=project.name,
                    connection=connection_name,
                    merge_mode=self.current_build_set.getMergeMode(),
                    refspec=refspec,
                    branch=branch,
                    ref=self.current_build_set.ref,
                    number=number,
                    patchset=patchset,
                    oldrev=oldrev,
                    newrev=newrev,
                    )


class Ref(object):
    """An existing state of a Project."""

    def __init__(self, project):
        self.project = project
        self.ref = None
        self.oldrev = None
        self.newrev = None

    def getBasePath(self):
        base_path = ''
        if hasattr(self, 'ref'):
            base_path = "%s/%s" % (self.newrev[:2], self.newrev)

        return base_path

    def _id(self):
        return self.newrev

    def __repr__(self):
        rep = None
        if self.newrev == '0000000000000000000000000000000000000000':
            rep = '<Ref 0x%x deletes %s from %s' % (
                  id(self), self.ref, self.oldrev)
        elif self.oldrev == '0000000000000000000000000000000000000000':
            rep = '<Ref 0x%x creates %s on %s>' % (
                  id(self), self.ref, self.newrev)
        else:
            # Catch all
            rep = '<Ref 0x%x %s updated %s..%s>' % (
                  id(self), self.ref, self.oldrev, self.newrev)

        return rep

    def equals(self, other):
        if (self.project == other.project
            and self.ref == other.ref
            and self.newrev == other.newrev):
            return True
        return False

    def isUpdateOf(self, other):
        return False

    def filterJobs(self, jobs):
        return filter(lambda job: job.changeMatches(self), jobs)

    def getRelatedChanges(self):
        return set()

    def updatesConfig(self):
        return False

    def getSafeAttributes(self):
        return Attributes(project=self.project,
                          ref=self.ref,
                          oldrev=self.oldrev,
                          newrev=self.newrev)


class Change(Ref):
    """A proposed new state for a Project."""
    def __init__(self, project):
        super(Change, self).__init__(project)
        self.branch = None
        self.number = None
        self.url = None
        self.patchset = None
        self.refspec = None

        self.files = []
        self.needs_changes = []
        self.needed_by_changes = []
        self.is_current_patchset = True
        self.can_merge = False
        self.is_merged = False
        self.failed_to_merge = False
        self.approvals = []
        self.open = None
        self.status = None
        self.owner = None

        self.source_event = None

    def _id(self):
        return '%s,%s' % (self.number, self.patchset)

    def __repr__(self):
        return '<Change 0x%x %s>' % (id(self), self._id())

    def getBasePath(self):
        if hasattr(self, 'refspec'):
            return "%s/%s/%s" % (
                str(self.number)[-2:], self.number, self.patchset)
        return super(Change, self).getBasePath()

    def equals(self, other):
        if self.number == other.number and self.patchset == other.patchset:
            return True
        return False

    def isUpdateOf(self, other):
        if ((hasattr(other, 'number') and self.number == other.number) and
            (hasattr(other, 'patchset') and
             self.patchset is not None and
             other.patchset is not None and
             int(self.patchset) > int(other.patchset))):
            return True
        return False

    def getRelatedChanges(self):
        related = set()
        for c in self.needs_changes:
            related.add(c)
        for c in self.needed_by_changes:
            related.add(c)
            related.update(c.getRelatedChanges())
        return related

    def updatesConfig(self):
        if 'zuul.yaml' in self.files or '.zuul.yaml' in self.files:
            return True
        return False

    def getSafeAttributes(self):
        return Attributes(project=self.project,
                          number=self.number,
                          patchset=self.patchset)


class PullRequest(Change):
    def __init__(self, project):
        super(PullRequest, self).__init__(project)
        self.updated_at = None
        self.title = None

    def isUpdateOf(self, other):
        if (hasattr(other, 'number') and self.number == other.number and
            hasattr(other, 'patchset') and self.patchset != other.patchset and
            hasattr(other, 'updated_at') and
            self.updated_at > other.updated_at):
            return True
        return False


class TriggerEvent(object):
    """Incoming event from an external system."""
    def __init__(self):
        self.data = None
        # common
        self.type = None
        # For management events (eg: enqueue / promote)
        self.tenant_name = None
        self.project_hostname = None
        self.project_name = None
        self.trigger_name = None
        # Representation of the user account that performed the event.
        self.account = None
        # patchset-created, comment-added, etc.
        self.change_number = None
        self.change_url = None
        self.patch_number = None
        self.refspec = None
        self.approvals = []
        self.branch = None
        self.comment = None
        self.label = None
        self.unlabel = None
        self.state = None
        # ref-updated
        self.ref = None
        self.oldrev = None
        self.newrev = None
        # timer
        self.timespec = None
        # zuultrigger
        self.pipeline_name = None
        # For events that arrive with a destination pipeline (eg, from
        # an admin command, etc):
        self.forced_pipeline = None

    @property
    def canonical_project_name(self):
        return self.project_hostname + '/' + self.project_name

    def __repr__(self):
        ret = '<TriggerEvent %s %s' % (self.type, self.canonical_project_name)

        if self.branch:
            ret += " %s" % self.branch
        if self.change_number:
            ret += " %s,%s" % (self.change_number, self.patch_number)
        if self.approvals:
            ret += ' ' + ', '.join(
                ['%s:%s' % (a['type'], a['value']) for a in self.approvals])
        ret += '>'

        return ret

    def isPatchsetCreated(self):
        return 'patchset-created' == self.type

    def isChangeAbandoned(self):
        return 'change-abandoned' == self.type


class GithubTriggerEvent(TriggerEvent):

    def __init__(self):
        super(GithubTriggerEvent, self).__init__()
        self.title = None

    def isPatchsetCreated(self):
        if self.type == 'pull_request':
            return self.action in ['opened', 'changed']
        return False

    def isChangeAbandoned(self):
        if self.type == 'pull_request':
            return 'closed' == self.action
        return False


class BaseFilter(object):
    """Base Class for filtering which Changes and Events to process."""
    def __init__(self, required_approvals=[], reject_approvals=[]):
        self._required_approvals = copy.deepcopy(required_approvals)
        self.required_approvals = self._tidy_approvals(required_approvals)
        self._reject_approvals = copy.deepcopy(reject_approvals)
        self.reject_approvals = self._tidy_approvals(reject_approvals)

    def _tidy_approvals(self, approvals):
        for a in approvals:
            for k, v in a.items():
                if k == 'username':
                    a['username'] = re.compile(v)
                elif k in ['email', 'email-filter']:
                    a['email'] = re.compile(v)
                elif k == 'newer-than':
                    a[k] = time_to_seconds(v)
                elif k == 'older-than':
                    a[k] = time_to_seconds(v)
            if 'email-filter' in a:
                del a['email-filter']
        return approvals

    def _match_approval_required_approval(self, rapproval, approval):
        # Check if the required approval and approval match
        if 'description' not in approval:
            return False
        now = time.time()
        by = approval.get('by', {})
        for k, v in rapproval.items():
            if k == 'username':
                if (not v.search(by.get('username', ''))):
                        return False
            elif k == 'email':
                if (not v.search(by.get('email', ''))):
                        return False
            elif k == 'newer-than':
                t = now - v
                if (approval['grantedOn'] < t):
                        return False
            elif k == 'older-than':
                t = now - v
                if (approval['grantedOn'] >= t):
                    return False
            else:
                if not isinstance(v, list):
                    v = [v]
                if (normalizeCategory(approval['description']) != k or
                        int(approval['value']) not in v):
                    return False
        return True

    def matchesApprovals(self, change):
        if (self.required_approvals and not change.approvals
                or self.reject_approvals and not change.approvals):
            # A change with no approvals can not match
            return False

        # TODO(jhesketh): If we wanted to optimise this slightly we could
        # analyse both the REQUIRE and REJECT filters by looping over the
        # approvals on the change and keeping track of what we have checked
        # rather than needing to loop on the change approvals twice
        return (self.matchesRequiredApprovals(change) and
                self.matchesNoRejectApprovals(change))

    def matchesRequiredApprovals(self, change):
        # Check if any approvals match the requirements
        for rapproval in self.required_approvals:
            matches_rapproval = False
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # We have a matching approval so this requirement is
                    # fulfilled
                    matches_rapproval = True
                    break
            if not matches_rapproval:
                return False
        return True

    def matchesNoRejectApprovals(self, change):
        # Check to make sure no approvals match a reject criteria
        for rapproval in self.reject_approvals:
            for approval in change.approvals:
                if self._match_approval_required_approval(rapproval, approval):
                    # A reject approval has been matched, so we reject
                    # immediately
                    return False
        # To get here no rejects can have been matched so we should be good to
        # queue
        return True


class EventFilter(BaseFilter):
    """Allows a Pipeline to only respond to certain events."""
    def __init__(self, trigger, types=[], branches=[], refs=[],
                 event_approvals={}, comments=[], emails=[], usernames=[],
                 timespecs=[], required_approvals=[], reject_approvals=[],
                 pipelines=[], actions=[], labels=[], unlabels=[], states=[],
                 ignore_deletes=True):
        super(EventFilter, self).__init__(
            required_approvals=required_approvals,
            reject_approvals=reject_approvals)
        self.trigger = trigger
        self._types = types
        self._branches = branches
        self._refs = refs
        self._comments = comments
        self._emails = emails
        self._usernames = usernames
        self._pipelines = pipelines
        self.types = [re.compile(x) for x in types]
        self.branches = [re.compile(x) for x in branches]
        self.refs = [re.compile(x) for x in refs]
        self.comments = [re.compile(x) for x in comments]
        self.emails = [re.compile(x) for x in emails]
        self.usernames = [re.compile(x) for x in usernames]
        self.pipelines = [re.compile(x) for x in pipelines]
        self.actions = actions
        self.event_approvals = event_approvals
        self.timespecs = timespecs
        self.labels = labels
        self.unlabels = unlabels
        self.states = states
        self.ignore_deletes = ignore_deletes

    def __repr__(self):
        ret = '<EventFilter'

        if self._types:
            ret += ' types: %s' % ', '.join(self._types)
        if self._pipelines:
            ret += ' pipelines: %s' % ', '.join(self._pipelines)
        if self._branches:
            ret += ' branches: %s' % ', '.join(self._branches)
        if self._refs:
            ret += ' refs: %s' % ', '.join(self._refs)
        if self.ignore_deletes:
            ret += ' ignore_deletes: %s' % self.ignore_deletes
        if self.event_approvals:
            ret += ' event_approvals: %s' % ', '.join(
                ['%s:%s' % a for a in self.event_approvals.items()])
        if self.required_approvals:
            ret += ' required_approvals: %s' % ', '.join(
                ['%s' % a for a in self._required_approvals])
        if self.reject_approvals:
            ret += ' reject_approvals: %s' % ', '.join(
                ['%s' % a for a in self._reject_approvals])
        if self._comments:
            ret += ' comments: %s' % ', '.join(self._comments)
        if self._emails:
            ret += ' emails: %s' % ', '.join(self._emails)
        if self._usernames:
            ret += ' username_filters: %s' % ', '.join(self._usernames)
        if self.timespecs:
            ret += ' timespecs: %s' % ', '.join(self.timespecs)
        if self.actions:
            ret += ' actions: %s' % ', '.join(self.actions)
        if self.labels:
            ret += ' labels: %s' % ', '.join(self.labels)
        if self.unlabels:
            ret += ' unlabels: %s' % ', '.join(self.unlabels)
        if self.states:
            ret += ' states: %s' % ', '.join(self.states)
        ret += '>'

        return ret

    def matches(self, event, change):
        # event types are ORed
        matches_type = False
        for etype in self.types:
            if etype.match(event.type):
                matches_type = True
        if self.types and not matches_type:
            return False

        # pipelines are ORed
        matches_pipeline = False
        for epipe in self.pipelines:
            if epipe.match(event.pipeline_name):
                matches_pipeline = True
        if self.pipelines and not matches_pipeline:
            return False

        # branches are ORed
        matches_branch = False
        for branch in self.branches:
            if branch.match(event.branch):
                matches_branch = True
        if self.branches and not matches_branch:
            return False

        # refs are ORed
        matches_ref = False
        if event.ref is not None:
            for ref in self.refs:
                if ref.match(event.ref):
                    matches_ref = True
        if self.refs and not matches_ref:
            return False
        if self.ignore_deletes and event.newrev == EMPTY_GIT_REF:
            # If the updated ref has an empty git sha (all 0s),
            # then the ref is being deleted
            return False

        # comments are ORed
        matches_comment_re = False
        for comment_re in self.comments:
            if (event.comment is not None and
                comment_re.search(event.comment)):
                matches_comment_re = True
        if self.comments and not matches_comment_re:
            return False

        # We better have an account provided by Gerrit to do
        # email filtering.
        if event.account is not None:
            account_email = event.account.get('email')
            # emails are ORed
            matches_email_re = False
            for email_re in self.emails:
                if (account_email is not None and
                        email_re.search(account_email)):
                    matches_email_re = True
            if self.emails and not matches_email_re:
                return False

            # usernames are ORed
            account_username = event.account.get('username')
            matches_username_re = False
            for username_re in self.usernames:
                if (account_username is not None and
                    username_re.search(account_username)):
                    matches_username_re = True
            if self.usernames and not matches_username_re:
                return False

        # approvals are ANDed
        for category, value in self.event_approvals.items():
            matches_approval = False
            for eapproval in event.approvals:
                if (normalizeCategory(eapproval['description']) == category and
                    int(eapproval['value']) == int(value)):
                    matches_approval = True
            if not matches_approval:
                return False

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
            return False

        # timespecs are ORed
        matches_timespec = False
        for timespec in self.timespecs:
            if (event.timespec == timespec):
                matches_timespec = True
        if self.timespecs and not matches_timespec:
            return False

        # actions are ORed
        matches_action = False
        for action in self.actions:
            if (event.action == action):
                matches_action = True
        if self.actions and not matches_action:
            return False

        # labels are ORed
        if self.labels and event.label not in self.labels:
            return False

        # unlabels are ORed
        if self.unlabels and event.unlabel not in self.unlabels:
            return False

        # states are ORed
        if self.states and event.state not in self.states:
            return False

        return True


class ChangeishFilter(BaseFilter):
    """Allows a Manager to only enqueue Changes that meet certain criteria."""
    def __init__(self, open=None, current_patchset=None,
                 statuses=[], required_approvals=[],
                 reject_approvals=[]):
        super(ChangeishFilter, self).__init__(
            required_approvals=required_approvals,
            reject_approvals=reject_approvals)
        self.open = open
        self.current_patchset = current_patchset
        self.statuses = statuses

    def __repr__(self):
        ret = '<ChangeishFilter'

        if self.open is not None:
            ret += ' open: %s' % self.open
        if self.current_patchset is not None:
            ret += ' current-patchset: %s' % self.current_patchset
        if self.statuses:
            ret += ' statuses: %s' % ', '.join(self.statuses)
        if self.required_approvals:
            ret += (' required_approvals: %s' %
                    str(self.required_approvals))
        if self.reject_approvals:
            ret += (' reject_approvals: %s' %
                    str(self.reject_approvals))
        ret += '>'

        return ret

    def matches(self, change):
        if self.open is not None:
            if self.open != change.open:
                return False

        if self.current_patchset is not None:
            if self.current_patchset != change.is_current_patchset:
                return False

        if self.statuses:
            if change.status not in self.statuses:
                return False

        # required approvals are ANDed (reject approvals are ORed)
        if not self.matchesApprovals(change):
            return False

        return True


class ProjectPipelineConfig(object):
    # Represents a project cofiguration in the context of a pipeline
    def __init__(self):
        self.job_list = JobList()
        self.queue_name = None
        self.merge_mode = None


class ProjectConfig(object):
    # Represents a project cofiguration
    def __init__(self, name):
        self.name = name
        self.merge_mode = None
        self.pipelines = {}
        self.private_key_file = None


class UnparsedAbideConfig(object):
    """A collection of yaml lists that has not yet been parsed into objects.

    An Abide is a collection of tenants.
    """

    def __init__(self):
        self.tenants = []

    def extend(self, conf):
        if isinstance(conf, UnparsedAbideConfig):
            self.tenants.extend(conf.tenants)
            return

        if not isinstance(conf, list):
            raise Exception("Configuration items must be in the form of "
                            "a list of dictionaries (when parsing %s)" %
                            (conf,))
        for item in conf:
            if not isinstance(item, dict):
                raise Exception("Configuration items must be in the form of "
                                "a list of dictionaries (when parsing %s)" %
                                (conf,))
            if len(item.keys()) > 1:
                raise Exception("Configuration item dictionaries must have "
                                "a single key (when parsing %s)" %
                                (conf,))
            key, value = item.items()[0]
            if key == 'tenant':
                self.tenants.append(value)
            else:
                raise Exception("Configuration item not recognized "
                                "(when parsing %s)" %
                                (conf,))


class UnparsedTenantConfig(object):
    """A collection of yaml lists that has not yet been parsed into objects."""

    def __init__(self):
        self.pipelines = []
        self.jobs = []
        self.project_templates = []
        self.projects = {}
        self.nodesets = []
        self.secrets = []
        self.semaphores = []

    def copy(self):
        r = UnparsedTenantConfig()
        r.pipelines = copy.deepcopy(self.pipelines)
        r.jobs = copy.deepcopy(self.jobs)
        r.project_templates = copy.deepcopy(self.project_templates)
        r.projects = copy.deepcopy(self.projects)
        r.nodesets = copy.deepcopy(self.nodesets)
        r.secrets = copy.deepcopy(self.secrets)
        r.semaphores = copy.deepcopy(self.semaphores)
        return r

    def extend(self, conf):
        if isinstance(conf, UnparsedTenantConfig):
            self.pipelines.extend(conf.pipelines)
            self.jobs.extend(conf.jobs)
            self.project_templates.extend(conf.project_templates)
            for k, v in conf.projects.items():
                self.projects.setdefault(k, []).extend(v)
            self.nodesets.extend(conf.nodesets)
            self.secrets.extend(conf.secrets)
            self.semaphores.extend(conf.semaphores)
            return

        if not isinstance(conf, list):
            raise Exception("Configuration items must be in the form of "
                            "a list of dictionaries (when parsing %s)" %
                            (conf,))

        for item in conf:
            if not isinstance(item, dict):
                raise Exception("Configuration items must be in the form of "
                                "a list of dictionaries (when parsing %s)" %
                                (conf,))
            if len(item.keys()) > 1:
                raise Exception("Configuration item dictionaries must have "
                                "a single key (when parsing %s)" %
                                (conf,))
            key, value = item.items()[0]
            if key == 'project':
                name = value['name']
                self.projects.setdefault(name, []).append(value)
            elif key == 'job':
                self.jobs.append(value)
            elif key == 'project-template':
                self.project_templates.append(value)
            elif key == 'pipeline':
                self.pipelines.append(value)
            elif key == 'nodeset':
                self.nodesets.append(value)
            elif key == 'secret':
                self.secrets.append(value)
            elif key == 'semaphore':
                self.semaphores.append(value)
            else:
                raise Exception("Configuration item `%s` not recognized "
                                "(when parsing %s)" %
                                (item, conf,))


class Layout(object):
    """Holds all of the Pipelines."""

    def __init__(self):
        self.tenant = None
        self.project_configs = {}
        self.project_templates = {}
        self.pipelines = OrderedDict()
        # This is a dictionary of name -> [jobs].  The first element
        # of the list is the first job added with that name.  It is
        # the reference definition for a given job.  Subsequent
        # elements are aspects of that job with different matchers
        # that override some attribute of the job.  These aspects all
        # inherit from the reference definition.
        self.jobs = {'noop': [Job('noop')]}
        self.nodesets = {}
        self.secrets = {}
        self.semaphores = {}

    def getJob(self, name):
        if name in self.jobs:
            return self.jobs[name][0]
        raise Exception("Job %s not defined" % (name,))

    def getJobs(self, name):
        return self.jobs.get(name, [])

    def addJob(self, job):
        # We can have multiple variants of a job all with the same
        # name, but these variants must all be defined in the same repo.
        prior_jobs = [j for j in self.getJobs(job.name) if
                      j.source_context.project !=
                      job.source_context.project]
        if prior_jobs:
            raise Exception("Job %s in %s is not permitted to shadow "
                            "job %s in %s" % (
                                job,
                                job.source_context.project,
                                prior_jobs[0],
                                prior_jobs[0].source_context.project))

        if job.name in self.jobs:
            self.jobs[job.name].append(job)
        else:
            self.jobs[job.name] = [job]

    def addNodeSet(self, nodeset):
        if nodeset.name in self.nodesets:
            raise Exception("NodeSet %s already defined" % (nodeset.name,))
        self.nodesets[nodeset.name] = nodeset

    def addSecret(self, secret):
        if secret.name in self.secrets:
            raise Exception("Secret %s already defined" % (secret.name,))
        self.secrets[secret.name] = secret

    def addSemaphore(self, semaphore):
        if semaphore.name in self.semaphores:
            raise Exception("Semaphore %s already defined" % (semaphore.name,))
        self.semaphores[semaphore.name] = semaphore

    def addPipeline(self, pipeline):
        self.pipelines[pipeline.name] = pipeline

    def addProjectTemplate(self, project_template):
        self.project_templates[project_template.name] = project_template

    def addProjectConfig(self, project_config):
        self.project_configs[project_config.name] = project_config

    def _createJobGraph(self, item, job_list, job_graph):
        change = item.change
        pipeline = item.pipeline
        for jobname in job_list.jobs:
            # This is the final job we are constructing
            frozen_job = None
            # Whether the change matches any globally defined variant
            matched = False
            for variant in self.getJobs(jobname):
                if variant.changeMatches(change):
                    if frozen_job is None:
                        frozen_job = variant.copy()
                        frozen_job.setRun()
                    else:
                        frozen_job.applyVariant(variant)
                    matched = True
            if not matched:
                # A change must match at least one defined job variant
                # (that is to say that it must match more than just
                # the job that is defined in the tree).
                continue
            # If the job does not allow auth inheritance, do not allow
            # the project-pipeline variants to update its execution
            # attributes.
            if frozen_job.auth and not frozen_job.auth.inherit:
                frozen_job.final = True
            # Whether the change matches any of the project pipeline
            # variants
            matched = False
            for variant in job_list.jobs[jobname]:
                if variant.changeMatches(change):
                    frozen_job.applyVariant(variant)
                    matched = True
            if not matched:
                # A change must match at least one project pipeline
                # job variant.
                continue
            if (frozen_job.allowed_projects and
                change.project.name not in frozen_job.allowed_projects):
                raise Exception("Project %s is not allowed to run job %s" %
                                (change.project.name, frozen_job.name))
            if ((not pipeline.allow_secrets) and frozen_job.auth and
                frozen_job.auth.secrets):
                raise Exception("Pipeline %s does not allow jobs with "
                                "secrets (job %s)" % (
                                    pipeline.name, frozen_job.name))
            job_graph.addJob(frozen_job)

    def createJobGraph(self, item):
        project_config = self.project_configs.get(
            item.change.project.canonical_name, None)
        ret = JobGraph()
        # NOTE(pabelanger): It is possible for a foreign project not to have a
        # configured pipeline, if so return an empty JobGraph.
        if project_config and item.pipeline.name in project_config.pipelines:
            project_job_list = \
                project_config.pipelines[item.pipeline.name].job_list
            self._createJobGraph(item, project_job_list, ret)
        return ret


class Semaphore(object):
    def __init__(self, name, max=1):
        self.name = name
        self.max = int(max)


class SemaphoreHandler(object):
    log = logging.getLogger("zuul.SemaphoreHandler")

    def __init__(self):
        self.semaphores = {}

    def acquire(self, item, job):
        if not job.semaphore:
            return True

        semaphore_key = job.semaphore

        m = self.semaphores.get(semaphore_key)
        if not m:
            # The semaphore is not held, acquire it
            self._acquire(semaphore_key, item, job.name)
            return True
        if (item, job.name) in m:
            # This item already holds the semaphore
            return True

        # semaphore is there, check max
        if len(m) < self._max_count(item, job.semaphore):
            self._acquire(semaphore_key, item, job.name)
            return True

        return False

    def release(self, item, job):
        if not job.semaphore:
            return

        semaphore_key = job.semaphore

        m = self.semaphores.get(semaphore_key)
        if not m:
            # The semaphore is not held, nothing to do
            self.log.error("Semaphore can not be released for %s "
                           "because the semaphore is not held" %
                           item)
            return
        if (item, job.name) in m:
            # This item is a holder of the semaphore
            self._release(semaphore_key, item, job.name)
            return
        self.log.error("Semaphore can not be released for %s "
                       "which does not hold it" % item)

    def _acquire(self, semaphore_key, item, job_name):
        self.log.debug("Semaphore acquire {semaphore}: job {job}, item {item}"
                       .format(semaphore=semaphore_key,
                               job=job_name,
                               item=item))
        if semaphore_key not in self.semaphores:
            self.semaphores[semaphore_key] = []
        self.semaphores[semaphore_key].append((item, job_name))

    def _release(self, semaphore_key, item, job_name):
        self.log.debug("Semaphore release {semaphore}: job {job}, item {item}"
                       .format(semaphore=semaphore_key,
                               job=job_name,
                               item=item))
        sem_item = (item, job_name)
        if sem_item in self.semaphores[semaphore_key]:
            self.semaphores[semaphore_key].remove(sem_item)

        # cleanup if there is no user of the semaphore anymore
        if len(self.semaphores[semaphore_key]) == 0:
            del self.semaphores[semaphore_key]

    @staticmethod
    def _max_count(item, semaphore_name):
        if not item.current_build_set.layout:
            # This should not occur as the layout of the item must already be
            # built when acquiring or releasing a semaphore for a job.
            raise Exception("Item {} has no layout".format(item))

        # find the right semaphore
        default_semaphore = Semaphore(semaphore_name, 1)
        semaphores = item.current_build_set.layout.semaphores
        return semaphores.get(semaphore_name, default_semaphore).max


class Tenant(object):
    def __init__(self, name):
        self.name = name
        self.layout = None
        # The unparsed configuration from the main zuul config for
        # this tenant.
        self.unparsed_config = None
        # The list of projects from which we will read full
        # configuration.
        self.config_projects = []
        # The unparsed config from those projects.
        self.config_projects_config = None
        # The list of projects from which we will read untrusted
        # in-repo configuration.
        self.untrusted_projects = []
        # The unparsed config from those projects.
        self.untrusted_projects_config = None
        self.semaphore_handler = SemaphoreHandler()

        # A mapping of project names to projects.  project_name ->
        # VALUE where VALUE is a further dictionary of
        # canonical_hostname -> Project.
        self.projects = {}
        self.canonical_hostnames = set()

    def _addProject(self, project):
        """Add a project to the project index

        :arg Project project: The project to add.
        """
        self.canonical_hostnames.add(project.canonical_hostname)
        hostname_dict = self.projects.setdefault(project.name, {})
        if project.canonical_hostname in hostname_dict:
            raise Exception("Project %s is already in project index" %
                            (project,))
        hostname_dict[project.canonical_hostname] = project

    def getProject(self, name):
        """Return a project given its name.

        :arg str name: The name of the project.  It may be fully
            qualified (E.g., "git.example.com/subpath/project") or may
            contain only the project name name may be supplied (E.g.,
            "subpath/project").

        :returns: A tuple (trusted, project) or (None, None) if the
            project is not found or ambiguous.  The "trusted" boolean
            indicates whether or not the project is trusted by this
            tenant.
        :rtype: (bool, Project)

        """
        path = name.split('/', 1)
        if path[0] in self.canonical_hostnames:
            hostname = path[0]
            project_name = path[1]
        else:
            hostname = None
            project_name = name
        hostname_dict = self.projects.get(project_name)
        project = None
        if hostname_dict:
            if hostname:
                project = hostname_dict.get(hostname)
            else:
                values = hostname_dict.values()
                if len(values) == 1:
                    project = values[0]
                else:
                    raise Exception("Project name '%s' is ambiguous, "
                                    "please fully qualify the project "
                                    "with a hostname" % (name,))
        if project is None:
            return (None, None)
        if project in self.config_projects:
            return (True, project)
        if project in self.untrusted_projects:
            return (False, project)
        # This should never happen:
        raise Exception("Project %s is neither trusted nor untrusted" %
                        (project,))

    def addConfigProject(self, project):
        self.config_projects.append(project)
        self._addProject(project)

    def addUntrustedProject(self, project):
        self.untrusted_projects.append(project)
        self._addProject(project)


class Abide(object):
    def __init__(self):
        self.tenants = OrderedDict()


class JobTimeData(object):
    format = 'B10H10H10B'
    version = 0

    def __init__(self, path):
        self.path = path
        self.success_times = [0 for x in range(10)]
        self.failure_times = [0 for x in range(10)]
        self.results = [0 for x in range(10)]

    def load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            data = struct.unpack(self.format, f.read())
        version = data[0]
        if version != self.version:
            raise Exception("Unkown data version")
        self.success_times = list(data[1:11])
        self.failure_times = list(data[11:21])
        self.results = list(data[21:32])

    def save(self):
        tmpfile = self.path + '.tmp'
        data = [self.version]
        data.extend(self.success_times)
        data.extend(self.failure_times)
        data.extend(self.results)
        data = struct.pack(self.format, *data)
        with open(tmpfile, 'w') as f:
            f.write(data)
        os.rename(tmpfile, self.path)

    def add(self, elapsed, result):
        elapsed = int(elapsed)
        if result == 'SUCCESS':
            self.success_times.append(elapsed)
            self.success_times.pop(0)
            result = 0
        else:
            self.failure_times.append(elapsed)
            self.failure_times.pop(0)
            result = 1
        self.results.append(result)
        self.results.pop(0)

    def getEstimatedTime(self):
        times = [x for x in self.success_times if x]
        if times:
            return float(sum(times)) / len(times)
        return 0.0


class TimeDataBase(object):
    def __init__(self, root):
        self.root = root
        self.jobs = {}

    def _getTD(self, name):
        td = self.jobs.get(name)
        if not td:
            td = JobTimeData(os.path.join(self.root, name))
            self.jobs[name] = td
            td.load()
        return td

    def getEstimatedTime(self, name):
        return self._getTD(name).getEstimatedTime()

    def update(self, name, elapsed, result):
        td = self._getTD(name)
        td.add(elapsed, result)
        td.save()
