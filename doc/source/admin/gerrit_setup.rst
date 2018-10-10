:orphan:

Gerrit
======

Installation
------------

Gerrit can be downloaded from the `Gerrit Code Review
<https:///www.gerritcodereview.com>`_ web site, and also contains
Gerrit documentation with installation instructions.

Create a Zuul User
------------------

The Gerrit documentation walks you through adding a first user, which
will end up being the admin user. Once the admin user is created, and
SSH access has been setup for that user, you can use that account to
create a new ``zuul`` user. This user, which will be used by our Zuul
installation, must have SSH access to gerrit, and have the
`stream-events <https://gerrit-review.googlesource.com/Documentation/access-control.html#global_capabilities>`_
ACL enabled.

.. TODO: Instructions to create the ssh key used here

As the admin user, create the ``zuul`` user, and import an SSH key for
``zuul``:

.. code-block:: shell

   cat $PUBKEY | ssh -p 29418 $USER@localhost gerrit create-account \
     --group "'Registered Users'" --ssh-key - zuul

``$PUBKEY`` is the location of the SSH public key for the ``zuul``
user. ``$USER`` is the username for the admin user.

The ``zuul`` user should now be able to stream events:

.. code-block:: shell

   ssh -p 29418 zuul@localhost gerrit stream-events

Configure Gerrit
----------------

The ``zuul`` user (and any other users you may create, for that
matter) will need to be able to leave review votes on any project
hosted in your Gerrit.  This is done with the use of Gerrit
`Review Labels <https://gerrit-review.googlesource.com/Documentation/access-control.html#category_review_labels>`_.
You may need to add the proper label permissions to the ``All-Projects``
project, which defines ACLs that all other projects will inherit.

.. TODO: Instructions to create a Verified label?

Visting `Projects` -> `List` -> `All-Projects` -> `Access` in your
Gerrit lets you see the current access permissions. In the
``Reference: refs/heads/*`` section, you will need to add a permisson
for the ``Label Code-Review`` for the ``Registered Users`` group (we
added the ``zuul`` user to this group when we created it).

.. note:: The label you configure here must match the label referenced in
          your Zuul pipeline definitions. We've chosen the Code-Review label
          here as an example.

Create a New Project
--------------------

The admin user can create new projects in Gerrit, which users can then clone
and use to submit code changes. Zuul will monitor the Gerrit event stream for
these submissions.

To create a new project named 'demo-project':

.. code-block:: shell

   ssh -p 29418 $USER@localhost gerrit create-project demo-project --empty-commit

Modify the Project
------------------

* Clone the project:

.. code-block:: shell

   git clone ssh://$USER@localhost:29418/demo-project.git

* Install the change ID hook that Gerrit requires:

.. code-block:: shell

   cd demo-project
   scp -p -P 29418 $USER@localhost:hooks/commit-msg .git/hooks/

* Now you are ready to modify the project and push the changes to Gerrit:

.. code-block:: shell

   echo "test" > README.txt
   git add .
   git commit -m "First commit"
   git push origin HEAD:refs/for/master

You should now be able to see your change in Gerrit.
