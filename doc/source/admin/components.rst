:title: Components

.. _components:

Components
==========

Zuul is a distributed system consisting of several components, each of
which is described below.


.. graphviz::
   :align: center

   graph  {
      node [shape=box]
      Gearman [shape=ellipse]
      Gerrit [fontcolor=grey]
      Zookeeper [shape=ellipse]
      Nodepool
      GitHub [fontcolor=grey]

      Merger -- Gearman
      Executor -- Gearman
      Web -- Gearman

      Gearman -- Scheduler;
      Scheduler -- Gerrit;
      Scheduler -- Zookeeper;
      Zookeeper -- Nodepool;
      Scheduler -- GitHub;
   }



All Zuul processes read the ``/etc/zuul/zuul.conf`` file (an alternate
location may be supplied on the command line) which uses an INI file
syntax.  Each component may have its own configuration file, though
you may find it simpler to use the same file for all components.

An example ``zuul.conf``:

.. code-block:: ini

   [gearman]
   server=localhost

   [gearman_server]
   start=true
   log_config=/etc/zuul/gearman-logging.yaml

   [zookeeper]
   hosts=zk1.example.com,zk2.example.com,zk3.example.com

   [webapp]
   status_url=https://zuul.example.com/status

   [scheduler]
   log_config=/etc/zuul/scheduler-logging.yaml

A minimal Zuul system may consist of a :ref:`scheduler` and
:ref:`executor` both running on the same host.  Larger installations
should consider running multiple executors, each on a dedicated host,
and running mergers on dedicated hosts as well.

Common
------

The following applies to all Zuul components.

Configuration
~~~~~~~~~~~~~

The following sections of ``zuul.conf`` are used by all Zuul components:


.. attr:: gearman

   Client connection information for Gearman.

   .. attr:: server
      :required:

      Hostname or IP address of the Gearman server.

   .. attr:: port
      :default: 4730

      Port on which the Gearman server is listening.

   .. attr:: ssl_ca

      An openssl file containing a set of concatenated “certification
      authority” certificates in PEM formet.

   .. attr:: ssl_cert

      An openssl file containing the client public certificate in PEM format.

   .. attr:: ssl_key

      An openssl file containing the client private key in PEM format.

.. attr:: statsd

   Information about the optional statsd server.  If the ``statsd``
   python module is installed and this section is configured,
   statistics will be reported to statsd.  See :ref:`statsd` for more
   information.

   .. attr:: server

      Hostname or IP address of the statsd server.

   .. attr:: port
      :default: 8125

      The UDP port on which the statsd server is listening.

   .. attr:: prefix

      If present, this will be prefixed to all of the keys before
      transmitting to the statsd server.

.. NOTE: this is a white lie at this point, since only the scheduler
   uses this, however, we expect other components to use it later, so
   it's reasonable for admins to plan for this now.

.. attr:: zookeeper

   Client connection information for ZooKeeper

   .. attr:: hosts
      :required:

      A list of zookeeper hosts for Zuul to use when communicating
      with Nodepool.

   .. attr:: session_timeout
      :default: 10.0

      The ZooKeeper session timeout, in seconds.


.. _scheduler:

Scheduler
---------

The scheduler is the primary component of Zuul.  The scheduler is not
a scalable component; one, and only one, scheduler must be running at
all times for Zuul to be operational.  It receives events from any
connections to remote systems which have been configured, enqueues
items into pipelines, distributes jobs to executors, and reports
results.

Configuration
~~~~~~~~~~~~~

The following sections of ``zuul.conf`` are used by the scheduler:


.. attr:: gearman_server

   The builtin gearman server. Zuul can fork a gearman process from
   itself rather than connecting to an external one.

   .. attr:: start
      :default: false

      Whether to start the internal Gearman server.

   .. attr:: listen_address
      :default: all addresses

      IP address or domain name on which to listen.

   .. attr:: port
      :default: 4730

      TCP port on which to listen.

   .. attr:: log_config

      Path to log config file for internal Gearman server.

   .. attr:: ssl_ca

      An openssl file containing a set of concatenated “certification
      authority” certificates in PEM formet.

   .. attr:: ssl_cert

      An openssl file containing the server public certificate in PEM
      format.

   .. attr:: ssl_key

      An openssl file containing the server private key in PEM format.

.. attr:: webapp

   .. attr:: listen_address
      :default: all addresses

      IP address or domain name on which to listen.

   .. attr:: port
      :default: 8001

      Port on which the webapp is listening.

   .. attr:: status_expiry
      :default: 1

      Zuul will cache the status.json file for this many seconds.

   .. attr:: status_url

      URL that will be posted in Zuul comments made to changes when
      starting jobs for a change.

      .. TODO: is this effectively required?

.. attr:: scheduler

   .. attr:: command_socket
      :default: /var/lib/zuul/scheduler.socket

      Path to command socket file for the scheduler process.

   .. attr:: tenant_config
      :required:

      Path to :ref:`tenant-config` file.

   .. attr:: log_config

      Path to log config file.

   .. attr:: pidfile
      :default: /var/run/zuul-schedurecr/zuul-scheduler.pid

      Path to PID lock file.

   .. attr:: state_dir
      :default: /var/lib/zuul

      Path to directory in which Zuul should save its state.

Operation
~~~~~~~~~

To start the scheduler, run ``zuul-scheduler``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

Most of Zuul's configuration is automatically updated as changes to
the repositories which contain it are merged.  However, Zuul must be
explicitly notified of changes to the tenant config file, since it is
not read from a git repository.  To do so, send the scheduler PID
(saved in the pidfile specified in the configuration) a `SIGHUP`
signal.

Merger
------

Mergers are an optional Zuul service; they are not required for Zuul
to operate, but some high volume sites may benefit from running them.
Zuul performs quite a lot of git operations in the course of its work.
Each change that is to be tested must be speculatively merged with the
current state of its target branch to ensure that it can merge, and to
ensure that the tests that Zuul perform accurately represent the
outcome of merging the change.  Because Zuul's configuration is stored
in the git repos it interacts with, and is dynamically evaluated, Zuul
often needs to perform a speculative merge in order to determine
whether it needs to perform any further actions.

All of these git operations add up, and while Zuul executors can also
perform them, large numbers may impact their ability to run jobs.
Therefore, administrators may wish to run standalone mergers in order
to reduce the load on executors.

Configuration
~~~~~~~~~~~~~

The following section of ``zuul.conf`` is used by the merger:

.. attr:: merger

   .. attr:: command_socket
      :default: /var/lib/zuul/merger.socket

      Path to command socket file for the merger process.

   .. attr:: git_dir

      Directory in which Zuul should clone git repositories.

   .. attr:: git_http_low_speed_limit
      :default: 1000

      If the HTTP transfer speed is less then git_http_low_speed_limit for
      longer then git_http_low_speed_time, the transfer is aborted.

      Value in bytes, setting to 0 will disable.

   .. attr:: git_http_low_speed_time
      :default: 30

      If the HTTP transfer speed is less then git_http_low_speed_limit for
      longer then git_http_low_speed_time, the transfer is aborted.

      Value in seconds, setting to 0 will disable.

   .. attr:: git_user_email

      Value to pass to `git config user.email
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

   .. attr:: git_user_name

      Value to pass to `git config user.name
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

   .. attr:: log_config

      Path to log config file for the merger process.

   .. attr:: pidfile
      :default: /var/run/zuul-merger/zuul-merger.pid

      Path to PID lock file for the merger process.

Operation
~~~~~~~~~

To start the merger, run ``zuul-merger``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

.. _executor:

Executor
--------

Executors are responsible for running jobs.  At the start of each job,
an executor prepares an environment in which to run Ansible which
contains all of the git repositories specified by the job with all
dependent changes merged into their appropriate branches.  The branch
corresponding to the proposed change will be checked out (in all
projects, if it exists).  Any roles specified by the job will also be
present (also with dependent changes merged, if appropriate) and added
to the Ansible role path.  The executor also prepares an Ansible
inventory file with all of the nodes requested by the job.

The executor also contains a merger.  This is used by the executor to
prepare the git repositories used by jobs, but is also available to
perform any tasks normally performed by standalone mergers.  Because
the executor performs both roles, small Zuul installations may not
need to run standalone mergers.

Trusted and Untrusted Playbooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The executor runs playbooks in one of two execution contexts depending
on whether the project containing the playbook is a
:term:`config-project` or an :term:`untrusted-project`.  If the
playbook is in a config project, the executor runs the playbook in the
*trusted* execution context, otherwise, it is run in the *untrusted*
execution context.

Both execution contexts use `bubblewrap`_ [#nullwrap]_ to create a
namespace to ensure that playbook executions are isolated and are unable
to access files outside of a restricted environment.  The administrator
may configure additional local directories on the executor to be made
available to the restricted environment.

The trusted execution context has access to all Ansible features,
including the ability to load custom Ansible modules.  Needless to
say, extra scrutiny should be given to code that runs in a trusted
context as it could be used to compromise other jobs running on the
executor, or the executor itself, especially if the administrator has
granted additional access through bubblewrap, or a method of escaping
the restricted environment created by bubblewrap is found.

Playbooks run in the untrusted execution context are not permitted to
load additional Ansible modules or access files outside of the
restricted environment prepared for them by the executor.  In addition
to the bubblewrap environment applied to both execution contexts, in
the untrusted context some standard Ansible modules are replaced with
versions which prohibit some actions, including attempts to access
files outside of the restricted execution context.  These redundant
protections are made as part of a defense-in-depth strategy.

.. _bubblewrap: https://github.com/projectatomic/bubblewrap
.. [#nullwrap] Unless one has set execution_wrapper to nullwrap in the
               executor configuration.

Configuration
~~~~~~~~~~~~~

The following sections of ``zuul.conf`` are used by the executor:

.. attr:: executor

   .. attr:: command_socket
      :default: /var/lib/zuul/executor.socket

      Path to command socket file for the executor process.

   .. attr:: finger_port
      :default: 7900

      Port to use for finger log streamer.

   .. attr:: git_dir
      :default: /var/lib/zuul/git

      Directory that Zuul should clone local git repositories to.  The
      executor keeps a local copy of every git repository it works
      with to speed operations and perform speculative merging.

      This should be on the same filesystem as
      :attr:`executor.job_dir` so that when git repos are cloned into
      the job workspaces, they can be hard-linked to the local git
      cache.

   .. attr:: job_dir
      :default: /tmp

      Directory that Zuul should use to hold temporary job directories.
      When each job is run, a new entry will be created under this
      directory to hold the configuration and scratch workspace for
      that job.  It will be deleted at the end of the job (unless the
      `--keep-jobdir` command line option is specified).

      This should be on the same filesystem as :attr:`executor.git_dir`
      so that when git repos are cloned into the job workspaces, they
      can be hard-linked to the local git cache.

   .. attr:: log_config

      Path to log config file for the executor process.

   .. attr:: pidfile
      :default: /var/run/zuul-executor/zuul-executor.pid

      Path to PID lock file for the executor process.

   .. attr:: private_key_file
      :default: ~/.ssh/id_rsa

      SSH private key file to be used when logging into worker nodes.

   .. _admin_sitewide_variables:

   .. attr:: variables

      Path to an Ansible variables file to supply site-wide variables.
      This should be a YAML-formatted file consisting of a single
      dictionary.  The contents will be made available to all jobs as
      Ansible variables.  These variables take precedence over all
      other forms (job variables and secrets).  Care should be taken
      when naming these variables to avoid potential collisions with
      those used by jobs.  Prefixing variable names with a
      site-specific identifier is recommended.  The default is not to
      add any site-wide variables.  See the :ref:`User's Guide
      <user_sitewide_variables>` for more information.

   .. attr:: disk_limit_per_job
      :default: 250

      This integer is the maximum number of megabytes that any one job
      is allowed to consume on disk while it is running. If a job's
      scratch space has more than this much space consumed, it will be
      aborted.

   .. attr:: trusted_ro_paths

      List of paths, separated by ``:`` to read-only bind mount into
      trusted bubblewrap contexts.

   .. attr:: trusted_rw_paths

      List of paths, separated by ``:`` to read-write bind mount into
      trusted bubblewrap contexts.

   .. attr:: untrusted_ro_paths

      List of paths, separated by ``:`` to read-only bind mount into
      untrusted bubblewrap contexts.

   .. attr:: untrusted_rw_paths

      List of paths, separated by ``:`` to read-write bind mount into
      untrusted bubblewrap contexts.

   .. attr:: execution_wrapper
      :default: bubblewrap

      Name of the execution wrapper to use when executing
      `ansible-playbook`. The default, `bubblewrap` is recommended for
      all installations.

      There is also a `nullwrap` driver for situations where one wants
      to run Zuul without access to bubblewrap or in such a way that
      bubblewrap may interfere with the jobs themselves. However,
      `nullwrap` is considered unsafe, as `bubblewrap` provides
      significant protections against malicious users and accidental
      breakage in playbooks. As such,  `nullwrap` is not recommended
      for use in production.
      
      This option, and thus, `nullwrap`, may be removed in the future.
      `bubblewrap` has become integral to securely operating Zuul.  If you
      have a valid use case for it, we encourage you to let us know.

   .. attr:: load_multiplier
      :default: 2.5

      When an executor host gets too busy, the system may suffer
      timeouts and other ill effects. The executor will stop accepting
      more than 1 job at a time until load has lowered below a safe
      level.  This level is determined by multiplying the number of
      CPU's by `load_multiplier`.

      So for example, if the system has 2 CPUs, and load_multiplier
      is 2.5, the safe load for the system is 5.00. Any time the
      system load average is over 5.00, the executor will quit
      accepting multiple jobs at one time.

      The executor will observe system load and determine whether
      to accept more jobs every 30 seconds.

   .. attr:: hostname
      :default: hostname of the server

      The executor needs to know its hostname under which it is reachable by
      zuul-web. Otherwise live console log streaming doesn't work. In most cases
      This is automatically detected correctly. But when running in environments
      where it cannot determine its hostname correctly this can be overridden
      here.

.. attr:: merger

   .. attr:: git_user_email

      Value to pass to `git config user.email
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

   .. attr:: git_user_name

      Value to pass to `git config user.name
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

Operation
~~~~~~~~~

To start the executor, run ``zuul-executor``.

There are several commands which can be run to control the executor's
behavior once it is running.

To stop the executor immediately, aborting all jobs (they may be
relaunched according to their retry policy), run ``zuul-executor
stop``.

To request that the executor stop executing new jobs and exit when all
currently running jobs have completed, run ``zuul-executor graceful``.

To enable or disable running Ansible in verbose mode (with the
``-vvv`` argument to ansible-playbook) run ``zuul-executor verbose``
and ``zuul-executor unverbose``.

Web Server
----------

The Zuul web server currently acts as a websocket interface to live log
streaming. Eventually, it will serve as the single process handling all
HTTP interactions with Zuul.

Configuration
~~~~~~~~~~~~~

In addition to the common configuration sections, the following
sections of ``zuul.conf`` are used by the web server:

.. attr:: web

   .. attr:: listen_address
      :default: 127.0.0.1

      IP address or domain name on which to listen.

   .. attr:: log_config

      Path to log config file for the web server process.

   .. attr:: pidfile
      :default: /var/run/zuul-web/zuul-web.pid

      Path to PID lock file for the web server process.

   .. attr:: port
      :default: 9000

      Port to use for web server process.

   .. attr:: websocket_url

      Base URL on which the websocket service is exposed, if different
      than the base URL of the web app.

   .. attr:: static_cache_expiry
      :default: 3600

      The Cache-Control max-age response header value for static files served
      by the zuul-web. Set to 0 during development to disable Cache-Control.

Operation
~~~~~~~~~

To start the web server, run ``zuul-web``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

Finger Gateway
--------------

The Zuul finger gateway listens on the standard finger port (79) for
finger requests specifying a build UUID for which it should stream log
results. The gateway will determine which executor is currently running that
build and query that executor for the log stream.

This is intended to be used with the standard finger command line client.
For example::

    finger UUID@zuul.example.com

The above would stream the logs for the build identified by `UUID`.

Configuration
~~~~~~~~~~~~~

In addition to the common configuration sections, the following
sections of ``zuul.conf`` are used by the finger gateway:

.. attr:: fingergw

   .. attr:: command_socket
      :default: /var/lib/zuul/fingergw.socket

      Path to command socket file for the executor process.

   .. attr:: listen_address
      :default: all addresses

      IP address or domain name on which to listen.

   .. attr:: log_config

      Path to log config file for the finger gateway process.

   .. attr:: pidfile
      :default: /var/run/zuul-fingergw/zuul-fingergw.pid

      Path to PID lock file for the finger gateway process.

   .. attr:: port
      :default: 79

      Port to use for the finger gateway. Note that since command line
      finger clients cannot usually specify the port, leaving this set to
      the default value is highly recommended.

   .. attr:: user
      :default: zuul

      User ID for the zuul-fingergw process. In normal operation as a
      daemon, the finger gateway should be started as the ``root`` user, but
      it will drop privileges to this user during startup.

Operation
~~~~~~~~~

To start the finger gateway, run ``zuul-fingergw``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.
