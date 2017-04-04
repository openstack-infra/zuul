# Copyright 2016 Red Hat, Inc.
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

import six


@six.add_metaclass(abc.ABCMeta)
class Driver(object):
    """A Driver is an extension component of Zuul that supports
    interfacing with a remote system.  It can support any of the following
    interfaces (but must support at least one to be useful):

    * ConnectionInterface
    * SourceInterface
    * TriggerInterface
    * ReporterInterface

    Zuul will create a single instance of each Driver (which will be
    shared by all tenants), and this instance will persist for the life of
    the process.  The Driver class may therefore manage any global state
    used by all connections.

    The class or instance attribute **name** must be provided as a string.

    """
    name = None

    def reconfigure(self, tenant):
        """Called when a tenant is reconfigured.

        This method is optional; the base implementation does nothing.

        When Zuul performs a reconfiguration for a tenant, this method
        is called with the tenant (including the new layout
        configuration) as an argument.  The driver may establish any
        global resources needed by the tenant at this point.

        :arg Tenant tenant: The :py:class:`zuul.model.Tenant` which has been
            reconfigured.

        """
        pass

    def registerScheduler(self, scheduler):
        """Register the scheduler with the driver.

        This method is optional; the base implementation does nothing.

        This method is called once during initialization to allow the
        driver to store a handle to the running scheduler.

        :arg Scheduler scheduler: The current running
           :py:class:`zuul.scheduler.Scheduler`.

        """
        pass

    def stop(self):
        """Stop the driver from running.

        This method is optional; the base implementation does nothing.

        This method is called when the connection registry is stopped
        allowing you additionally stop any running Driver computation
        not specific to a connection.
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class ConnectionInterface(object):
    """The Connection interface.

    A driver which is able to supply a Connection should implement
    this interface.

    """

    @abc.abstractmethod
    def getConnection(self, name, config):
        """Create and return a new Connection object.

        This method is required by the interface.

        This method will be called once for each connection specified
        in zuul.conf.  The resultant object should be responsible for
        establishing any long-lived connections to remote systems.  If
        Zuul is reconfigured, all existing connections will be stopped
        and this method will be called again for any new connections
        which should be created.

        When a connection is specified in zuul.conf with a name, that
        name is used here when creating the connection, and it is also
        used in the layout to attach triggers and reporters to the
        named connection.  If the Driver does not utilize a connection
        (because it does not interact with a remote system), do not
        implement this method and Zuul will automatically associate
        triggers and reporters with the name of the Driver itself
        where it would normally expect the name of a connection.

        :arg str name: The name of the connection.  This is the name
            supplied in the zuul.conf file where the connection is
            configured.
        :arg dict config: The configuration information supplied along
            with the connection in zuul.conf.

        :returns: A new Connection object.
        :rtype: Connection

        """
        pass


@six.add_metaclass(abc.ABCMeta)
class TriggerInterface(object):
    """The trigger interface.

    A driver which is able to supply a trigger should implement this
    interface.

    """

    @abc.abstractmethod
    def getTrigger(self, connection, config=None):
        """Create and return a new trigger object.

        This method is required by the interface.

        The trigger object returned should inherit from the
        :py:class:`~zuul.trigger.BaseTrigger` class.

        :arg Connection connection: The Connection object associated
            with the trigger (as previously returned by getConnection)
            or None.
        :arg dict config: The configuration information supplied along
            with the trigger in the layout.

        :returns: A new trigger object.
        :rtype: :py:class:`~zuul.trigger.BaseTrigger`

        """
        pass

    @abc.abstractmethod
    def getTriggerSchema(self):
        """Get the schema for this driver's trigger.

        This method is required by the interface.

        :returns: A voluptuous schema.
        :rtype: dict or Schema

        """
        pass


@six.add_metaclass(abc.ABCMeta)
class SourceInterface(object):
    """The source interface to be implemented by a driver.

    A driver which is able to supply a Source should implement this
    interface.

    """

    @abc.abstractmethod
    def getSource(self, connection):
        """Create and return a new Source object.

        This method is required by the interface.

        :arg Connection connection: The Connection object associated
            with the source (as previously returned by getConnection).

        :returns: A new Source object.
        :rtype: Source

        """
        pass

    @abc.abstractmethod
    def getRequireSchema(self):
        """Get the schema for this driver's pipeline requirement filter.

        This method is required by the interface.

        :returns: A voluptuous schema.
        :rtype: dict or Schema

        """
        pass

    @abc.abstractmethod
    def getRejectSchema(self):
        """Get the schema for this driver's pipeline reject filter.

        This method is required by the interface.

        :returns: A voluptuous schema.
        :rtype: dict or Schema

        """
        pass


@six.add_metaclass(abc.ABCMeta)
class ReporterInterface(object):
    """The reporter interface to be implemented by a driver.

    A driver which is able to supply a Reporter should implement this
    interface.

    """

    @abc.abstractmethod
    def getReporter(self, connection, config=None):
        """Create and return a new Reporter object.

        This method is required by the interface.

        :arg Connection connection: The Connection object associated
            with the reporter (as previously returned by getConnection)
            or None.
        :arg dict config: The configuration information supplied along
            with the reporter in the layout.

        :returns: A new Reporter object.
        :rtype: Reporter

        """
        pass

    @abc.abstractmethod
    def getReporterSchema(self):
        """Get the schema for this driver's reporter.

        This method is required by the interface.

        :returns: A voluptuous schema.
        :rtype: dict or Schema

        """
        pass


@six.add_metaclass(abc.ABCMeta)
class WrapperInterface(object):
    """The wrapper interface to be implmeneted by a driver.

    A driver which wraps execution of commands executed by Zuul should
    implement this interface.

    """

    @abc.abstractmethod
    def getPopen(self, **kwargs):
        """Create and return a subprocess.Popen factory wrapped however the
        driver sees fit.

        This method is required by the interface

        :arg dict kwargs: key/values for use by driver as needed

        :returns: a callable that takes the same args as subprocess.Popen
        :rtype: Callable
        """
        pass
