:title: Merger

Merger
======

The Zuul Merger is a separate component which communicates with the
main Zuul server via Gearman.  Its purpose is to speculatively merge
the changes for Zuul in preparation for testing.  The resulting git
commits also must be served to the test workers, and the server(s)
running the Zuul Merger are expected to do this as well.  Because both
of these tasks are resource intensive, any number of Zuul Mergers can
be run in parallel on distinct hosts.

Configuration
~~~~~~~~~~~~~

The Zuul Merger can read the same zuul.conf file as the main Zuul
server and requires the ``gearman``, ``gerrit``, ``merger``, and
``zuul`` sections (indicated fields only).  Be sure the zuul_url is
set appropriately on each host that runs a zuul-merger.

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
is available to workers (such as Jenkins).  This is accomplished by
serving Zuul's Git repositories directly.

Serving Zuul Git Repos
~~~~~~~~~~~~~~~~~~~~~~

Zuul maintains its own copies of any needed Git repositories in the
directory specified by ``git_dir`` in the ``merger`` section of
zuul.conf (by default, /var/lib/zuul/git).  To directly serve Zuul's
Git repositories in order to provide Zuul refs for workers, you can
configure Apache to do so using the following directives::

  SetEnv GIT_PROJECT_ROOT /var/lib/zuul/git
  SetEnv GIT_HTTP_EXPORT_ALL

  AliasMatch ^/p/(.*/objects/[0-9a-f]{2}/[0-9a-f]{38})$ /var/lib/zuul/git/$1
  AliasMatch ^/p/(.*/objects/pack/pack-[0-9a-f]{40}.(pack|idx))$ /var/lib/zuul/git/$1
  ScriptAlias /p/ /usr/lib/git-core/git-http-backend/

Note that Zuul's Git repositories are not bare, which means they have
a working tree, and are not suitable for public consumption (for
instance, a clone will produce a repository in an unpredictable state
depending on what the state of Zuul's repository is when the clone
happens).  They are, however, suitable for automated systems that
respond to Zuul triggers.

Clearing old references
~~~~~~~~~~~~~~~~~~~~~~~

The references created under refs/zuul are not garbage collected. Since
git fetch send them all to Gerrit to sync the repositories, the time
spent on merge will slightly grow overtime and start being noticeable.

To clean them you can use the ``tools/zuul-clear-refs.py`` script on
each repositories. It will delete Zuul references that point to commits
for which the commit date is older than a given amount of days (default
360)::

  ./tools/zuul-clear-refs.py /path/to/zuul/git/repo
