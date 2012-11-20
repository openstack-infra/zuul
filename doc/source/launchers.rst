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
You will need this later when configuring Zuul.  Appropriate user
permissions must be set under the Jenkins security matrix: under the
``Global`` group of permissions, check ``Read``, then under the ``Job``
group of permissions, check ``Read`` and  ``Build``. Finally, under
``Run`` check ``Update``.  If using a per project matrix, make sure the
user permissions are properly set for any jobs that you want Zuul to
trigger.

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

**ZUUL_UUID**
  Zuul provided key to link builds with Gerrit events
**ZUUL_REF**
  Zuul provided ref that includes commit(s) to build
**ZUUL_COMMIT**
  The commit SHA1 at the head of ZUUL_REF

Those are the only required parameters.  The ZUUL_UUID is needed for Zuul to
keep track of the build, and the ZUUL_REF and ZUUL_COMMIT parameters are for
use in preparing the git repo for the build.

.. note::
    The GERRIT_PROJECT and UUID parameters are deprecated respectively in
    favor of ZUUL_PROJECT and ZUUL_UUID.

The following parameters will be sent for all builds, but are not required so
you do not need to configure Jenkins to accept them if you do not plan on using
them:

**ZUUL_PROJECT**
  The project that triggered this build
**ZUUL_PIPELINE**
  The Zuul pipeline that is building this job

The following parameters are optional and will only be provided for
builds associated with changes (i.e., in response to patchset-created
or comment-added events):

**ZUUL_BRANCH**
  The target branch for the change that triggered this build
**ZUUL_CHANGE**
  The Gerrit change ID for the change that triggered this build
**ZUUL_CHANGE_IDS**
  All of the Gerrit change IDs that are included in this build (useful
  when the DependentPipelineManager combines changes for testing)
**ZUUL_PATCHSET**
  The Gerrit patchset number for the change that triggered this build

The following parameters are optional and will only be provided for
post-merge (ref-updated) builds:

**ZUUL_OLDREV**
  The SHA1 of the old revision at this ref (recall the ref name is
  in ZUUL_REF)
**ZUUL_NEWREV**
  The SHA1 of the new revision at this ref (recall the ref name is
  in ZUUL_REF)
**ZUUL_SHORT_OLDREV**
  The shortened (7 character) SHA1 of the old revision
**ZUUL_SHORT_NEWREV**
  The shortened (7 character) SHA1 of the new revision

In order to test the correct build, configure the Jenkins Git SCM
plugin as follows::

  Source Code Management:
    Git
      Repositories:
        Repository URL:  <your Gerrit or Zuul repository URL>
          Advanced:
            Refspec: ${ZUUL_REF}
      Branches to build:
        Branch Specifier: ${ZUUL_COMMIT}
	  Advanced:
	    Clean after checkout: True

That should be sufficient for a job that only builds a single project.
If you have multiple interrelated projects (i.e., they share a Zuul
Change Queue) that are built together, you may be able to configure
the Git plugin to prepare them, or you may chose to use a shell script
instead.  The OpenStack project uses the following script to prepare
the workspace for its integration testing:

  https://github.com/openstack-ci/devstack-gate/blob/master/devstack-vm-gate-wrap.sh
