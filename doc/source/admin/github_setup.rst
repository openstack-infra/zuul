:orphan:

GitHub
======

Configure GitHub
----------------

The recommended way to use Zuul with GitHub is by creating a GitHub
App.  This allows you to easily add it to GitHub projects, and reduces
the likelihood of running into GitHub rate limits.  You'll need an
organization in Github for this, so create one if you haven't already.
In this example we will use `my-org`.

.. NOTE Duplicate content here and in drivers/github.rst.  Keep them
   in sync.

Create a `GitHub application
<https://developer.github.com/apps/building-integrations/setting-up-and-registering-github-apps/registering-github-apps/>`_:

* Go to your organization settings page to create the application, e.g.:
  https://github.com/organizations/my-org/settings/apps/new
* Set GitHub App name to "my-org-zuul"
* Set Setup URL to your setup documentation, when users install the application
  they are redirected to this url
* Set Webhook URL to
  ``http://<IP ADDRESS>:9000/api/connection/github/payload``.
* Create a Webhook secret, and record it for later use
* Set permissions:

  * Repository administration: Read
  * Repository contents: Read & Write (write to let zuul merge change)
  * Issues: Read & Write
  * Pull requests: Read & Write
  * Commit statuses: Read & Write

* Set events subscription:

  * Commit comment
  * Create
  * Push
  * Release
  * Issue comment
  * Issues
  * Label
  * Pull request
  * Pull request review
  * Pull request review comment
  * Status

* Set Where can this GitHub App be installed to "Any account"
* Create the App
* Generate a Private key in the app settings page and save the file
  for later


.. TODO See if we can script this using GitHub API

Go back to the `General` settings page for the app,
https://github.com/organizations/my-org/settings/apps/my-org-zuul
and look for the app `ID` number, under the `About` section.

Edit ``/etc/zuul/zuul.conf`` to add the following:

.. code-block:: shell

   sudo bash -c "cat >> /etc/zuul/zuul.conf <<EOF

   [connection github]
   driver=github
   app_id=<APP ID NUMBER>
   app_key=/etc/zuul/github.pem
   webhook_token=<WEBHOOK SECRET>
   EOF"

Upload the private key which was generated earlier, and save it in
``/etc/zuul/github.pem``.

Restart all of Zuul:

.. code-block:: shell

   sudo systemctl restart zuul-executor.service
   sudo systemctl restart zuul-web.service
   sudo systemctl restart zuul-scheduler.service

Go to the `Advanced` tab for the app in GitHub,
https://github.com/organizations/my-org/settings/apps/my-org-zuul/advanced,
and look for the initial ping from the app.  It probably wasn't
delivered since Zuul wasn't configured at the time, so click
``Resend`` and verify that it is delivered now that Zuul is
configured.

Create two new repositories in your org.  One will hold the
configuration for this tenant in Zuul, the other should be a normal
project repo to use for testing.  We'll call them ``zuul-test-config``
and ``zuul-test``, respectively.

Visit the public app page on GitHub,
https://github.com/apps/my-org-zuul, and install the app into your org.

Edit ``/etc/zuul/main.yaml`` so that it looks like this:

.. code-block:: yaml

   - tenant:
       name: quickstart
       source:
         zuul-git:
           config-projects:
             - zuul-base-jobs
           untrusted-projects:
             - zuul-jobs
         github:
           config-projects:
             - my-org/zuul-test-config
           untrusted-projects:
             - my-org/zuul-test

The first section, under ``zuul-git`` imports the standard library of
Zuul jobs that we configured earlier.  This adds a number of jobs that
you can immediately use in your Zuul installation.

The second section is your GitHub configuration.

After updating the file, restart the Zuul scheduler:

.. code-block:: shell

   sudo systemctl restart zuul-scheduler.service

Add an initial pipeline configuration to the `zuul-test-config`
repository.  Inside that project, create a ``zuul.yaml`` file with the
following contents:

.. code-block:: yaml

   - pipeline:
       name: check
       description: |
         Newly opened pull requests enter this pipeline to receive an
         initial verification
       manager: independent
       trigger:
         github:
           - event: pull_request
             action:
               - opened
               - changed
               - reopened
           - event: pull_request
             action: comment
             comment: (?i)^\s*recheck\s*$
       start:
         github:
           status: pending
           comment: false
       success:
         github:
           status: 'success'
       failure:
         github:
           status: 'failure'

Merge that commit into the repository.

In the `zuul-test` project, create a `.zuul.yaml` file with the
following contents:

.. code-block:: yaml

   - project:
       check:
         jobs:
           - noop

Open a new pull request with that commit against the `zuul-test`
project and verify that Zuul reports a successful run of the `noop`
job.
