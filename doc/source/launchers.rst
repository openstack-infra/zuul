.. _launchers:
:title: Launchers

Launchers
=========

Zuul has a modular architecture for launching jobs.  Currently only
Jenkins is supported, but it should be fairly easy to add a module to
support other systems.  Zuul makes very few assumptions about the
interface to a launcher -- if it can trigger jobs, cancel them, and
receive success or failure reports, it should be able to be used with
Zuul.  Patches to this effect are welcome.

Jenkins
-------

Zuul works with Jenkins using the Jenkins API and the notification
module.  It uses the Jenkins API to trigger jobs, passing in
parameters indicating what should be tested.  It recieves
notifications on job completion via the notification API (so jobs must
be conifigured to notify Zuul).

Jenkins Configuration
~~~~~~~~~~~~~~~~~~~~~

Zuul will need access to a Jenkins user.  Create a user in Jenkins,
and then visit the configuration page for the user:

  https://jenkins.example.com/user/USERNAME/configure

And click **Show API Token** to retrieve the API token for that user.
You will need this later when configuring Zuul.  Make sure that this
user has appropriate permission to build any jobs that you want Zuul
to trigger.

Make sure the notification plugin is installed.  Visit the plugin
manager on your jenkins:

  https://jenkins.example.com/pluginManager/

And install **Jenkins Notification plugin**.  The homepage for the
plugin is at:

  https://wiki.jenkins-ci.org/display/JENKINS/Notification+Plugin

Jenkins Job Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

For each job that you want Zuul to trigger, you will need to add a
notification endpoint for the job on that job's configuration page.
Click **Add Endpoint** and enter the following values:

**Protocol**
    ``HTTP``
**URL**
    ``http://127.0.0.1:8001/jenkins_endpoint``

If you are running Zuul on a different server than Jenkins, enter the
appropriate URL.  Note that Zuul itself has no access controls, so
ensure that only Jenkins is permitted to access that URL.

Zuul will pass some parameters to Jenkins for every job it launches.
Check **This build is parameterized**, and add the following fields
with the type **String Parameter**:

**UUID**
  Zuul provided key to link builds with Gerrit events
**GERRIT_PROJECT**
  Zuul provided project name
**GERRIT_BRANCH**
  Zuul provided branch name
**GERRIT_CHANGES**
  Zuul provided list of dependent changes to merge

You may find it useful to use the ``GERRIT_*`` variables in your job.
In particular, ``GERRIT_CHANGES`` indicates the change or changes that
should be tested.  If Zuul has decided that more than one change
should be merged and tested together, they will all be listed in
``GERRIT_CHANGES``.  The format for the description of one change is::

  project:branch:refspec

And multiple changes are separated by a carat ("^").  E.g.::

  testproject:master:refs/changes/20/420/1^testproject:master:refs/changes/21/421/1"

The OpenStack project uses the following script to update the
repository in a workspace and merge appropriate changes:

  https://github.com/openstack/openstack-ci-puppet/blob/master/modules/jenkins/files/slave_scripts/gerrit-git-prep.sh

Gerrit events that do not include a change (e.g., ref-updated events
which are emitted after a git ref is updated (i.e., a commit is merged
to master)) require a slightly different set of parameters:

**UUID**
  Zuul provided key to link builds with Gerrit events
**GERRIT_PROJECT**
  Zuul provided project name
**GERRIT_REFNAME**
  Zuul provided ref name
**GERRIT_OLDREV**
  Zuul provided old reference for ref-updated
**GERRIT_NEWREV**
    Zuul provided new reference for ref-updated

