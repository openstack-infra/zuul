#!/usr/bin/env python
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

import json
import logging
import six
import time
from kazoo.client import KazooClient, KazooState
from kazoo import exceptions as kze

# States:
# We are building this node but it is not ready for use.
BUILDING = 'building'
# The node is ready for use.
READY = 'ready'
# The node should be deleted.
DELETING = 'deleting'

STATES = set([BUILDING, READY, DELETING])


class ZooKeeperConnectionConfig(object):
    '''
    Represents the connection parameters for a ZooKeeper server.
    '''

    def __eq__(self, other):
        if isinstance(other, ZooKeeperConnectionConfig):
            if other.__dict__ == self.__dict__:
                return True
        return False

    def __init__(self, host, port=2181, chroot=None):
        '''Initialize the ZooKeeperConnectionConfig object.

        :param str host: The hostname of the ZooKeeper server.
        :param int port: The port on which ZooKeeper is listening.
            Optional, default: 2181.
        :param str chroot: A chroot for this connection.  All
            ZooKeeper nodes will be underneath this root path.
            Optional, default: None.

        (one per server) defining the ZooKeeper cluster servers. Only
        the 'host' attribute is required.'.

        '''
        self.host = host
        self.port = port
        self.chroot = chroot or ''


def buildZooKeeperHosts(host_list):
    '''
    Build the ZK cluster host list for client connections.

    :param list host_list: A list of
        :py:class:`~nodepool.zk.ZooKeeperConnectionConfig` objects (one
        per server) defining the ZooKeeper cluster servers.
    '''
    if not isinstance(host_list, list):
        raise Exception("'host_list' must be a list")
    hosts = []
    for host_def in host_list:
        host = '%s:%s%s' % (host_def.host, host_def.port, host_def.chroot)
        hosts.append(host)
    return ",".join(hosts)


class BaseModel(object):
    def __init__(self, o_id):
        if o_id:
            self.id = o_id
        self._state = None
        self.state_time = None
        self.stat = None

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        if not isinstance(value, six.string_types):
            raise TypeError("'id' attribute must be a string type")
        self._id = value

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if value not in STATES:
            raise TypeError("'%s' is not a valid state" % value)
        self._state = value
        self.state_time = time.time()

    def toDict(self):
        '''
        Convert a BaseModel object's attributes to a dictionary.
        '''
        d = {}
        d['state'] = self.state
        d['state_time'] = self.state_time
        return d

    def fromDict(self, d):
        '''
        Set base attributes based on the given dict.

        Unlike the derived classes, this should NOT return an object as it
        assumes self has already been instantiated.
        '''
        if 'state' in d:
            self.state = d['state']
        if 'state_time' in d:
            self.state_time = d['state_time']


class NodeRequest(BaseModel):
    '''
    Class representing a node request.
    '''

    def __init__(self, id=None):
        super(NodeRequest, self).__init__(id)

    def __repr__(self):
        d = self.toDict()
        d['id'] = self.id
        d['stat'] = self.stat
        return '<NodeRequest %s>' % d

    def toDict(self):
        '''
        Convert a NodeRequest object's attributes to a dictionary.
        '''
        d = super(NodeRequest, self).toDict()
        return d

    @staticmethod
    def fromDict(d, o_id=None):
        '''
        Create a NodeRequest object from a dictionary.

        :param dict d: The dictionary.
        :param str o_id: The object ID.

        :returns: An initialized ImageBuild object.
        '''
        o = NodeRequest(o_id)
        super(NodeRequest, o).fromDict(d)
        return o


class ZooKeeper(object):
    '''
    Class implementing the ZooKeeper interface.

    This class uses the facade design pattern to keep common interaction
    with the ZooKeeper API simple and consistent for the caller, and
    limits coupling between objects. It allows for more complex interactions
    by providing direct access to the client connection when needed (though
    that is discouraged). It also provides for a convenient entry point for
    testing only ZooKeeper interactions.
    '''

    log = logging.getLogger("zuul.zk.ZooKeeper")

    REQUEST_ROOT = '/nodepool/requests'

    def __init__(self):
        '''
        Initialize the ZooKeeper object.
        '''
        self.client = None
        self._became_lost = False

    def _dictToStr(self, data):
        return json.dumps(data)

    def _strToDict(self, data):
        return json.loads(data)

    def _connection_listener(self, state):
        '''
        Listener method for Kazoo connection state changes.

        .. warning:: This method must not block.
        '''
        if state == KazooState.LOST:
            self.log.debug("ZooKeeper connection: LOST")
            self._became_lost = True
        elif state == KazooState.SUSPENDED:
            self.log.debug("ZooKeeper connection: SUSPENDED")
        else:
            self.log.debug("ZooKeeper connection: CONNECTED")

    @property
    def connected(self):
        return self.client.state == KazooState.CONNECTED

    @property
    def suspended(self):
        return self.client.state == KazooState.SUSPENDED

    @property
    def lost(self):
        return self.client.state == KazooState.LOST

    @property
    def didLoseConnection(self):
        return self._became_lost

    def resetLostFlag(self):
        self._became_lost = False

    def connect(self, host_list, read_only=False):
        '''
        Establish a connection with ZooKeeper cluster.

        Convenience method if a pre-existing ZooKeeper connection is not
        supplied to the ZooKeeper object at instantiation time.

        :param list host_list: A list of
            :py:class:`~nodepool.zk.ZooKeeperConnectionConfig` objects
            (one per server) defining the ZooKeeper cluster servers.
        :param bool read_only: If True, establishes a read-only connection.

        '''
        if self.client is None:
            hosts = buildZooKeeperHosts(host_list)
            self.client = KazooClient(hosts=hosts, read_only=read_only)
            self.client.add_listener(self._connection_listener)
            self.client.start()

    def disconnect(self):
        '''
        Close the ZooKeeper cluster connection.

        You should call this method if you used connect() to establish a
        cluster connection.
        '''
        if self.client is not None and self.client.connected:
            self.client.stop()
            self.client.close()
            self.client = None

    def resetHosts(self, host_list):
        '''
        Reset the ZooKeeper cluster connection host list.

        :param list host_list: A list of
            :py:class:`~nodepool.zk.ZooKeeperConnectionConfig` objects
            (one per server) defining the ZooKeeper cluster servers.
        '''
        if self.client is not None:
            hosts = buildZooKeeperHosts(host_list)
            self.client.set_hosts(hosts=hosts)

    def submitNodeRequest(self, node_request):
        '''
        Submit a request for nodes to Nodepool.

        :param NodeRequest node_request: A NodeRequest with the
            contents of the request.
        '''
        priority = 100  # TODO(jeblair): integrate into nodereq

        data = node_request.toDict()
        data['created_time'] = time.time()

        path = '%s/%s-' % (self.REQUEST_ROOT, priority)
        self.log.debug(data)
        path = self.client.create(path, self._dictToStr(data),
                                  makepath=True,
                                  sequence=True, ephemeral=True)
        reqid = path.split("/")[-1]
        node_request.id = reqid

    def getNodeRequest(self, node_request, watcher):
        '''
        Read the specified node request and update its values.

        :param NodeRequest node_request: A NodeRequest to be read.  It
            will be updated with the results of the read.
        :param callable watcher: A watch function to be called when the
            node request is updated.
        '''

        path = '%s/%s' % (self.REQUEST_ROOT, node_request.id)
        try:
            data, stat = self.client.get(path, watch=watcher)
        except kze.NoNodeError:
            return
        data = self._strToDict(data)
        node_request.updateFromDict(data)
        # TODOv3(jeblair): re-register watches on disconnect
