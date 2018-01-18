Zuul
====

Zuul is a project gating system developed for the OpenStack Project.

We are currently engaged in a significant development effort in
preparation for the third major version of Zuul.  We call this effort
`Zuul v3`_ and it is described in more detail below.

The latest documentation for Zuul v3 is published at:
https://docs.openstack.org/infra/zuul/feature/zuulv3/

If you are looking for the Edge routing service named Zuul that is
related to Netflix, it can be found here:
https://github.com/Netflix/zuul

If you are looking for the Javascript testing tool named Zuul, it
can be found here:
https://github.com/defunctzombie/zuul

Contributing
------------

We are currently engaged in a significant development effort in
preparation for the third major version of Zuul.  We call this effort
`Zuul v3`_ and it is described in this file in the `feature/zuulv3`
branch of this repo.

To browse the latest code, see: https://git.openstack.org/cgit/openstack-infra/zuul/tree/
To clone the latest code, use `git clone git://git.openstack.org/openstack-infra/zuul`

Bugs are handled at: https://storyboard.openstack.org/#!/project/679

Code reviews are, as you might expect, handled by gerrit at
https://review.openstack.org

Use `git review` to submit patches (after creating a Gerrit account
that links to your launchpad account). Example::

    # Do your commits
    $ git review
    # Enter your username if prompted

Zuul v3
-------

The Zuul v3 effort involves significant changes to Zuul, and its
companion program, Nodepool.  The intent is for Zuul to become more
generally useful outside of the OpenStack community.  This is the best
way to get started with this effort:

1) Read the Zuul v3 spec: http://specs.openstack.org/openstack-infra/infra-specs/specs/zuulv3.html

   We use specification documents like this to describe large efforts
   where we want to make sure that all the participants are in
   agreement about what will happen and generally how before starting
   development.  These specs should contain enough information for
   people to evaluate the proposal generally, and sometimes include
   specific details that need to be agreed upon in advance.  They are
   living documents which can change as work gets underway.  However,
   every change or detail does not need to be reflected in the spec --
   most work is simply done with patches (and revised if necessary in
   code review).

2) Read the Nodepool build-workers spec: http://specs.openstack.org/openstack-infra/infra-specs/specs/nodepool-zookeeper-workers.html

3) Review any proposed updates to these specs: https://review.openstack.org/#/q/status:open+project:openstack-infra/infra-specs+topic:zuulv3

   Some of the information in the specs may be effectively superceded
   by changes here, which are still undergoing review.

4) Read developer documentation on the internal data model and testing: http://docs.openstack.org/infra/zuul/feature/zuulv3/developer.html

   The general philosophy for Zuul tests is to perform functional
   testing of either the individual component or the entire end-to-end
   system with external systems (such as Gerrit) replaced with fakes.
   Before adding additional unit tests with a narrower focus, consider
   whether they add value to this system or are merely duplicative of
   functional tests.

5) Review open changes: https://review.openstack.org/#/q/status:open+branch:feature/zuulv3

   We find that the most valuable code reviews are ones that spot
   problems with the proposed change, or raise questions about how
   that might affect other systems or subsequent work.  It is also a
   great way to stay involved as a team in work performed by others
   (for instance, by observing and asking questions about development
   while it is in progress).  We try not to sweat the small things and
   don't worry too much about style suggestions or other nitpicky
   things (unless they are relevant -- for instance, a -1 vote on a
   change that introduces a yaml change out of character with existing
   conventions is useful because it makes the system more
   user-friendly; a -1 vote on a change which uses a sub-optimal line
   breaking strategy is probably not the best use of anyone's time).

6) Join #zuul on Freenode.  Let others (especially jeblair who is
   trying to coordinate and prioritize work) know what you would like
   to work on.

7) Check storyboard for status of current work items: https://storyboard.openstack.org/#!/board/41

   Work items tagged with ``low-hanging-fruit`` are tasks that have
   been identified as not requiring an expansive knowledge of the
   system.  They may still require either some knowledge or
   investigation into a specific area, but should be suitable for a
   developer who is becoming acquainted with the system.  Those items
   can be found at:
   https://storyboard.openstack.org/#!/story/list?tags=low-hanging-fruit&tags=zuulv3

Once you are up to speed on those items, it will be helpful to know
the following:

* Zuul v3 includes some substantial changes to Zuul, and in order to
  implement them quickly and simultaneously, we temporarily disabled
  most of the test suite.  That test suite still has relevance, but
  tests are likely to need updating individually, with reasons ranging
  from something simple such as a test-framework method changing its
  name, to more substantial issues, such as a feature being removed as
  part of the v3 work.  Each test will need to be evaluated
  individually.  Feel free to, at any time, claim a test name in this
  story and work on re-enabling it:
  https://storyboard.openstack.org/#!/story/2000773

* Because of the importance of external systems, as well as the number
  of internal Zuul components, actually running Zuul in a development
  mode quickly becomes unweildy (imagine uploading changes to Gerrit
  repeatedly while altering Zuul source code).  Instead, the best way
  to develop with Zuul is in fact to write a functional test.
  Construct a test to fully simulate the series of events you want to
  see, then run it in the foreground.  For example::

    .tox/py27/bin/python -m testtools.run tests.unit.test_scheduler.TestScheduler.test_jobs_executed

  See TESTING.rst for more information.

* There are many occasions, when working on sweeping changes to Zuul
  v3, we left notes for future work items in the code marked with
  "TODOv3".  These represent potentially serious missing functionality
  or other issues which must be resolved before an initial v3 release
  (unlike a more conventional TODO note, these really can not be left
  indefinitely).  These present an opportunity to identify work items
  not otherwise tracked.  The names associated with TODO or TODOv3
  items do not mean that only that person can address them -- they
  simply reflect who to ask to explain the item in more detail if it
  is too cryptic.  In your own work, feel free to leave TODOv3 notes
  if a change would otherwise become too large or unweildy.

Python Version Support
----------------------

Zuul v3 requires Python 3. It does not support Python 2.

As Ansible is used for the execution of jobs, it's important to note that
while Ansible does support Python 3, not all of Ansible's modules do. Zuul
currently sets ``ansible_python_interpreter`` to python2 so that remote
content will be executed with Python2.

Roadmap
-------

* Begin using Zuul v3 to run jobs for Zuul itself
* Implement a shim to translate Zuul v2 demand into Nodepool Zookeeper
  launcher requests
* Begin using Zookeeper based Nodepool launchers with Zuul v2.5 in
  OpenStack Infra
* Move OpenStack Infra to use Zuul v3
* Implement Github support
* Begin using Zuul v3 to run tests on Ansible repos
* Implement support in Nodepool for non-OpenStack clouds
* Add native container support to Zuul / Nodepool
