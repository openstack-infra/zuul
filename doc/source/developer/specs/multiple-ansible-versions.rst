Multiple Ansible versions
=========================

.. warning:: This is not authoritative documentation.  These features
   are not currently available in Zuul.  They may change significantly
   before final implementation, or may never be fully completed.

Currently zuul only supports one specific ansible version at once. This
complicates upgrading ansible because ansible often breaks backwards
compatibility and so we need to synchronize the upgrade on the complete
deployment which is often not possible.

Instead we want to support multiple ansible versions at once so we can handle
the lifecycle of ansible versions by adding new versions and deprecating old
ones.


Requirements
------------

We want jobs to be able to pick a specific ansible version to run. However as we
have lots of stuff that overrides things in ansible we will let the job only
select a minor version (e.g. 2.6) in a list of supported versions. This is also
necessary from a security point of view so the user cannot pick a specific
bugfix version that is known to contain certain security flaws. Zuul needs to
support a list of specific minor versions from where it will pick the latest
bugfix version or a pinned version if we need to.

We need virtual environments for ansible which are not relocatable. Because of
this we must install ansible after the installation. Further we need to support
sdist based installations as well as wheel based installations. However wheel
based installations don't have any possibility for post install hooks. Thus
to stay consistent we will require to manually run a post installation script
to install the ansible versions. This script will work standalone as well as
within the executor process context. This will make it possible to let the
executor optionally install ansible at startup time if there is interest.
This can be useful for the quick start. However the recommended way will be the
manual run.

We also need a configuration that specifies additional packages that need to
be installed along with ansible. This is required because different deployers
use different ansible connections or modules that have additional optional
dependencies (e.g. winrm).


Job configuration
-----------------

There will be a new job attribute ``ansible-version`` that will instruct zuul
to take the specified version. This attribute will be validated against a list
of supported ansible versions that zuul currently can handle. Zuul will throw
a configuration error if a job selects an unsupported or unparsable version.
If no ``ansible-version`` is defined zuul will pick up the ansible version
marked as default. We will also need a mechanism to deprecate ansible versions
to prepare removing old versions. We could add labels to the supported versions.
To express that. The supported versions we will start with will be:

* 2.5 (deprecated)
* 2.6
* 2.7 (default)

The default ansible version will be configurable on global and tenant level.
This way updating the default to newer versions can be made much less
disruptive. Being able to specify the default version on tenant level makes
it easy to canary release ansible updates in a larger multi tenant environment.

We will also need to be able to pin a version to a specific bugfix version in
case the latest one is known to be broken. This will also be handled by the
installation mechanisms described below.


Installing ansible
------------------

We currently pull in ansible via the ``requirements.txt``. This will no longer
be sufficient. Instead zuul itself needs to take care of installing the
supported versions into a pre-defined directory structure using the venv module.
The executor will have two new config options:

* ``ansible-root``: The root path where ansible installations will be found. The
  default will be ``<exec-root>/lib/zuul/executor-ansible``. All supported
  ansible installations will live inside a venv in the path
  ``ansible-root/<minor-version>``.

* ``manage-ansible``: A boolean flag that tells the executor manage the
  installed ansible versions itself. The default will be ``true``.

  If set to ``true`` the executor will install and upgrade all supported
  ansible versions on startup.

  If set to ``false`` the executor will validate the presence of all supported
  ansible versions on startup and throw an error on missing installations.

The management of the ansible installations will be performed by a script
installed along the zuul binaries. This will install and update every supported
version of ansible into a specified ``ansible-root`` directory.

This script
can then be used by the executor or externally depending on the configuration.


Dockerized deployment
---------------------

In a dockerized deployment it is preferable to pre-install ansible during the
image build. This can be done by calling the installation script during the
image build. The official images will contain all supported versions.


Ansible module overrides
------------------------

We currently have many ansible module overrides. These may or may not be
targeted to a specific ansible version. Currently they are organized into the
folder ``zuul/ansible``. In order to support multiple ansible versions without
needing to fork everything there this will be reorganized into:

* ``zuul/ansible/generic``: Overrides and modules valid for all supported
   ansible versions.
* ``zuul/ansible/<version>``: Overrides and modules valid for a specific
  version.

If there are overrides that are valid for a range of ansible versions we can
define it in the lowest version and make use of symlinking to the other versions
in order to minimize additional maintenance overhead by not forking an override
where possible. Generally we should strive for having as much as possible in the
generic part to minimize the maintenance effort of these.


Deprecation policy
------------------

We should handle deprecating and removing supported ansible versions similar to
the deprecation policy described in zuul-jobs:
https://zuul-ci.org/docs/zuul-jobs/policy.html

Further we should make sure that whenever we release a new version of zuul we
should make sure that the list of supported ansible versions is a subset of
what is supported by ansible at that time. The list of supported ansible
versions can be found here:
https://docs.ansible.com/ansible/latest/reference_appendices/release_and_maintenance.html#release-status

We also should notify the users when they use deprecated ansible versions. This
can be done in two ways. First the executor will emit a warning to the logs when
it encounters a job that uses a deprecated ansible version. The executor already
can return warnings together with the build result. These will be added directly
to the reporting to the code review system. This can be used to warn about
deprecated ansible versions at a prominent location instead of burying it
somewhere in megabytes of logs.


Testing
-------

We also have a set of tests that validate the security overrides. We need to
test them for all supported ansible versions. Where needed we also need to fork
or add additional version specific tests.
