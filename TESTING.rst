===========================
Testing Your OpenStack Code
===========================
------------
A Quickstart
------------

This is designed to be enough information for you to run your first tests.
Detailed information on testing can be found here: https://wiki.openstack.org/wiki/Testing

*Install pip*::

  [apt-get | yum] install python-pip
More information on pip here: http://www.pip-installer.org/en/latest/

*Use pip to install tox*::

  pip install tox

Run The Tests
-------------

*Navigate to the project's root directory and execute*::

  tox
Note: completing this command may take a long time (depends on system resources)
also, you might not see any output until tox is complete.

Information about tox can be found here: http://testrun.org/tox/latest/


Run The Tests in One Environment
--------------------------------

Tox will run your entire test suite in the environments specified in the project tox.ini::

  [tox]

  envlist = <list of available environments>

To run the test suite in just one of the environments in envlist execute::

  tox -e <env>
so for example, *run the test suite in py26*::

  tox -e py26

Run One Test
------------

To run individual tests with tox::

  tox -e <env> -- path.to.module.Class.test

For example, to *run the basic Zuul test*::

  tox -e py27 -- tests.test_scheduler.TestScheduler.test_jobs_launched

To *run one test in the foreground* (after previously having run tox
to set up the virtualenv)::

  .tox/py27/bin/python -m testtools.run tests.test_scheduler.TestScheduler.test_jobs_launched

Need More Info?
---------------

More information about testr: https://wiki.openstack.org/wiki/Testr

More information about nose: https://nose.readthedocs.org/en/latest/


More information about testing OpenStack code can be found here:
https://wiki.openstack.org/wiki/Testing
