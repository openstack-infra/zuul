:title: Triggers

Triggers
========

The process of merging a change starts with proposing a change to be
merged.  Currently Zuul only supports Gerrit as a triggering system.
Zuul's design is modular, so alternate triggering and reporting
systems can be supported.  However, Gerrit has a particularly robust
data model, and Zuul does make some assumptions that include that data
model.  Nonetheless, patches to support alternate systems are welcome.

Gerrit
------

Zuul works with standard versions of Gerrit by invoking the ``gerrit
stream-events`` command over an SSH connection.  It also reports back
to Gerrit using SSH.

Gerrit Configuration
~~~~~~~~~~~~~~~~~~~~

Zuul will need access to a Gerrit user.  Consider naming the user
*Jenkins* so that developers see that feedback from changes is from
Jenkins (Zuul attempts to stay out of the way of developers, most
shouldn't even need to know it's there).

Create an SSH keypair for Zuul to use if there isn't one already, and
create a Gerrit user with that key::

  cat ~/id_rsa.pub | ssh -p29418 gerrit.example.com gerrit create-account --ssh-key - --full-name Jenkins jenkins

Give that user whatever permissions will be needed on the projects you
want Zuul to gate.  For instance, you may want to grant ``Verified
+/-1`` and ``Submit`` to the user.  Additional categories or values may
be added to Gerrit.  Zuul is very flexible and can take advantage of
those.

Zuul References
~~~~~~~~~~~~~~~

As the DependentPipelineManager may combine several changes together
for testing when performing speculative execution, determining exactly
how the workspace should be set up when running a Job can be complex.
To alleviate this problem, Zuul performs merges itself, merging or
cherry-picking changes as required and identifies the result with a
Git reference of the form ``refs/zuul/<branch>/Z<random sha1>``.
Preparing the workspace is then a simple matter of fetching that ref
and checking it out.  The parameters that provide this information are
described in :ref:`launchers`.

These references need to be made available via a Git repository that
is available to Jenkins.  You may accomplish this by either allowing
Zuul to push the references back to Gerrit, in which case you may
simply use the Gerrit Git repository.  If you do not have access to
the Gerrit repository, or would prefer Zuul not push its refs there,
you may directly serve the Git repositories that Zuul uses, and
configure Jenkins to use those.  Instructions for each of these
alternatives are in the following sections.

Pushing to Gerrit
"""""""""""""""""

If you want to push Zuul refs back to Gerrit, set the following
permissions for your project (or ``All-Projects``) in Gerrit (where
``CI Tools`` is a group of which the user you created above is a
member)::

    [access "refs/zuul/*"]
            create = group CI Tools
            push = +force CI Tools
            pushMerge = group CI Tools
    [access "refs/for/refs/zuul/*"]
            pushMerge = group CI Tools

And set ``push_change_refs`` to ``true`` in the ``zuul`` section of
zuul.conf.

Serving Zuul Git Repos
""""""""""""""""""""""

Zuul maintains its own copies of any needed Git repositories in the
directory specified by ``git_dir`` in the ``zuul`` section of
zuul.conf (by default, /var/lib/zuul/git).  If you want to serve
Zuul's Git repositories in order to provide Zuul refs for Jenkins, you
can configure Apache to do so using the following directives::

  SetEnv GIT_PROJECT_ROOT /var/lib/zuul/git
  SetEnv GIT_HTTP_EXPORT_ALL

  AliasMatch ^/p/(.*/objects/[0-9a-f]{2}/[0-9a-f]{38})$ /var/lib/zuul/git/$1
  AliasMatch ^/p/(.*/objects/pack/pack-[0-9a-f]{40}.(pack|idx))$ /var/lib/zuul/git/$1
  ScriptAlias /p/ /usr/lib/git-core/git-http-backend/

And set ``push_change_refs`` to ``false`` (the default) in the
``zuul`` section of zuul.conf.

Note that Zuul's Git repositories are not bare, which means they have
a working tree, and are not suitable for public consumption (for
instance, a clone will produce a repository in an unpredictable state
depending on what the state of Zuul's repository is when the clone
happens).  They are, however, suitable for automated systems that
respond to Zuul triggers.
