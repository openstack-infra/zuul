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
      Database [fontcolor=grey]
      Gearman [shape=ellipse]
      Gerrit [fontcolor=grey]
      Statsd [shape=ellipse fontcolor=grey]
      Zookeeper [shape=ellipse]
      Nodepool
      GitHub [fontcolor=grey]

      Merger -- Gearman
      Executor -- Gearman
      Executor -- Statsd
      Web -- Database
      Web -- Gearman
      Web -- Zookeeper
      Web -- Executor
      Finger -- Gearman
      Finger -- Executor

      Gearman -- Scheduler;
      Scheduler -- Database;
      Scheduler -- Gerrit;
      Scheduler -- Zookeeper;
      Zookeeper -- Nodepool;
      Scheduler -- GitHub;
      Scheduler -- Statsd;
   }

Each of the Zuul processes may run on the same host, or different
hosts.  Within Zuul, the components communicate with the scheduler via
the Gearman protocol, so each Zuul component needs to be able to
connect to the host running the Gearman server (the scheduler has a
built-in Gearman server which is recommended) on the Gearman port --
TCP port 4730 by default.

The Zuul scheduler communicates with Nodepool via the ZooKeeper
protocol.  Nodepool requires an external ZooKeeper cluster, and the
Zuul scheduler needs to be able to connect to the hosts in that
cluster on TCP port 2181.

Both the Nodepool launchers and Zuul executors need to be able to
communicate with the hosts which nodepool provides.  If these are on
private networks, the Executors will need to be able to route traffic
to them.

Only Zuul fingergw and Zuul web need to be publicly accessible;
executors never do. Executors should be accessible on TCP port 7900
by fingergw and web.

A database is only required if you create an sql driver in your Zuul
connections configuration. Both Zuul scheduler and Zuul web will need
access to it.

If statsd is enabled, the executors and scheduler needs to be able to
emit data to statsd.  Statsd can be configured to run on each host
and forward data, or services may emit to a centralized statsd
collector.  Statsd listens on UDP port 8125 by default.

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

   [web]
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

The scheduler includes a Gearman server which is used to communicate
with other components of Zuul.  It is possible to use an external
Gearman server, but the built-in server is well-tested and
recommended.  If the built-in server is used, other Zuul hosts will
need to be able to connect to the scheduler on the Gearman port, TCP
port 4730.  It is also strongly recommended to use SSL certs with
Gearman, as secrets are transferred from the scheduler to executors
over this link.

The scheduler must be able to connect to the ZooKeeper cluster used by
Nodepool in order to request nodes.  It does not need to connect
directly to the nodes themselves, however -- that function is handled
by the Executors.

It must also be able to connect to any services for which connections
are configured (Gerrit, GitHub, etc).

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

.. attr:: web

   .. attr:: status_url

      URL that will be posted in Zuul comments made to changes when
      starting jobs for a change.

      .. TODO: is this effectively required?

.. attr:: scheduler

   .. attr:: command_socket
      :default: /var/lib/zuul/scheduler.socket

      Path to command socket file for the scheduler process.

   .. attr:: tenant_config

      Path to :ref:`tenant-config` file. This attribute
      is exclusive with :attr:`scheduler.tenant_config_script`.

   .. attr:: tenant_config_script

      Path to a script to execute and load the tenant
      config from. This attribute is exclusive with
      :attr:`scheduler.tenant_config`.

   .. attr:: default_ansible_version

      Default ansible version to use for jobs that doesn't specify a version.
      See :attr:`job.ansible-version` for details.

   .. attr:: log_config

      Path to log config file.

   .. attr:: pidfile
      :default: /var/run/zuul/scheduler.pid

      Path to PID lock file.

   .. attr:: state_dir
      :default: /var/lib/zuul

      Path to directory in which Zuul should save its state.

   .. attr:: relative_priority
      :default: False

      A boolean which indicates whether the scheduler should supply
      relative priority information for node requests.

      In all cases, each pipeline may specify a precedence value which
      is used by Nodepool to satisfy requests from higher-precedence
      pipelines first.  If ``relative_priority`` is set to ``True``,
      then Zuul will additionally group items in the same pipeline by
      pipeline queue and weight each request by its position in that
      project's group.  A request for the first change in a given
      queue will have the highest relative priority, and the second
      change a lower relative priority.  The first change of each
      queue in a pipeline has the same relative priority, regardless
      of the order of submission or how many other changes are in the
      pipeline.  This can be used to make node allocations complete
      faster for projects with fewer changes in a system dominated by
      projects with more changes.

      If this value is ``False`` (the default), then node requests are
      sorted by pipeline precedence followed by the order in which
      they were submitted.  If this is ``True``, they are sorted by
      pipeline precedence, followed by relative priority, and finally
      the order in which they were submitted.

Operation
~~~~~~~~~

To start the scheduler, run ``zuul-scheduler``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

Most of Zuul's configuration is automatically updated as changes to
the repositories which contain it are merged.  However, Zuul must be
explicitly notified of changes to the tenant config file, since it is
not read from a git repository.  To do so, run
``zuul-scheduler full-reconfigure``. The signal based method by sending
a `SIGHUP` signal to the scheduler PID is deprecated.


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

Mergers need to be able to connect to the Gearman server (usually the
scheduler host) as well as any services for which connections are
configured (Gerrit, GitHub, etc).

Configuration
~~~~~~~~~~~~~

The following section of ``zuul.conf`` is used by the merger:

.. attr:: merger

   .. attr:: command_socket
      :default: /var/lib/zuul/merger.socket

      Path to command socket file for the merger process.

   .. attr:: git_dir
      :default: /var/lib/zuul/merger-git

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

   .. attr:: git_timeout
      :default: 300

      Timeout for git clone and fetch operations. This can be useful when
      dealing with large repos. Note that large timeouts can increase startup
      and reconfiguration times if repos are not cached so be cautious when
      increasing this value.

      Value in seconds.

   .. attr:: git_user_email

      Value to pass to `git config user.email
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

   .. attr:: git_user_name

      Value to pass to `git config user.name
      <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup>`_.

   .. attr:: log_config

      Path to log config file for the merger process.

   .. attr:: pidfile
      :default: /var/run/zuul/merger.pid

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

Executors need to be able to connect to the Gearman server (usually
the scheduler host), any services for which connections are configured
(Gerrit, GitHub, etc), as well as directly to the hosts which Nodepool
provides.

Trusted and Untrusted Playbooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The executor runs playbooks in one of two execution contexts depending
on whether the project containing the playbook is a
:term:`config-project` or an :term:`untrusted-project`.  If the
playbook is in a config project, the executor runs the playbook in the
*trusted* execution context, otherwise, it is run in the *untrusted*
execution context.

Both execution contexts use `bubblewrap`_ [#nullwrap]_ to create a namespace to
ensure that playbook executions are isolated and are unable to access
files outside of a restricted environment.  The administrator may
configure additional local directories on the executor to be made
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

.. _zuul-discuss: http://lists.zuul-ci.org/cgi-bin/mailman/listinfo/zuul-discuss

.. [#nullwrap] `bubblewrap` is integral to securely operating Zuul.
      If it is difficult for you to use it in your environment, we
      encourage you to let us know via the `zuul-discuss`_ mailing
      list.


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

   .. attr:: state_dir
      :default: /var/lib/zuul

      Path to directory in which Zuul should save its state.

   .. attr:: git_dir
      :default: /var/lib/zuul/executor-git

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
      :default: /var/run/zuul/executor.pid

      Path to PID lock file for the executor process.

   .. attr:: private_key_file
      :default: ~/.ssh/id_rsa

      SSH private key file to be used when logging into worker nodes.

   .. attr:: default_username
      :default: zuul

      Username to use when logging into worker nodes, if none is
      supplied by Nodepool.

   .. attr:: winrm_cert_key_file
      :default: ~/.winrm/winrm_client_cert.key

      The private key file of the client certificate to use for winrm
      connections to Windows nodes.

   .. attr:: winrm_cert_pem_file
      :default: ~/.winrm/winrm_client_cert.pem

      The certificate file of the client certificate to use for winrm
      connections to Windows nodes.

      .. note:: Currently certificate verification is disabled when
                connecting to Windows nodes via winrm.

   .. attr:: winrm_operation_timeout_sec
      :default: None. The Ansible default of 20 is used in this case.

      The timeout for WinRM operations.

   .. attr:: winrm_read_timeout_sec
      :default: None. The Ansible default of 30 is used in this case.

      The timeout for WinRM read. Increase this if there are intermittent
      network issues and read timeout errors keep occurring.

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
      <user_jobs_sitewide_variables>` for more information.

   .. attr:: manage_ansible
      :default: True

      Specifies wether the zuul-executor should install the supported ansible
      versions during startup or not. If this is ``True`` the zuul-executor
      will install the ansible versions into :attr:`executor.ansible_root`.

      It is recommended to set this to ``False`` and manually install Ansible
      after the Zuul installation by running ``zuul-manage-ansible``. This has
      the advantage that possible errors during Ansible installation can be
      spotted earlier. Further especially containerized deployments of Zuul
      will have the advantage of predictable versions.

   .. attr:: ansible_root
      :default: <state_dir>/ansible-bin

      Specifies where the zuul-executor should look for its supported ansible
      installations. By default it looks in the following directories and uses
      the first which it can find.

      * ``<zuul_install_dir>/lib/zuul/ansible``
      * ``<ansible_root>``

      The ``ansible_root`` setting allows you to override the second location
      which is also used for installation if ``manage_ansible`` is ``True``.

   .. attr:: ansible_setup_timeout
      :default: 60

      Timeout of the ansible setup playbook in seconds that runs before
      the first playbook of the job.

   .. attr:: disk_limit_per_job
      :default: 250

      This integer is the maximum number of megabytes that any one job
      is allowed to consume on disk while it is running. If a job's
      scratch space has more than this much space consumed, it will be
      aborted. Set to -1 to disable the limit.

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

   .. attr:: min_avail_hdd
      :default: 5.0

      This is the minimum percentage of HDD storage available for the
      :attr:`executor.state_dir` directory. The executor will stop accepting
      more than 1 job at a time until more HDD storage is available. The
      available HDD percentage is calculated from the total available
      disk space divided by the total real storage capacity multiplied by
      100.

   .. attr:: min_avail_mem
      :default: 5.0

      This is the minimum percentage of system RAM available. The
      executor will stop accepting more than 1 job at a time until
      more memory is available. The available memory percentage is
      calculated from the total available memory divided by the
      total real memory multiplied by 100. Buffers and cache are
      considered available in the calculation.

   .. attr:: hostname
      :default: hostname of the server

      The executor needs to know its hostname under which it is reachable by
      zuul-web. Otherwise live console log streaming doesn't work. In most cases
      This is automatically detected correctly. But when running in environments
      where it cannot determine its hostname correctly this can be overridden
      here.

   .. attr:: zone
      :default: None

      Name of the nodepool executor-zone to exclusively execute all jobs that
      have nodes with the specified executor-zone attribute.  As an example,
      it is possible for nodepool nodes to exist in a cloud with out public
      accessable IP address. By adding an executor to a zone nodepool nodes
      could be configured to use private ip addresses.

      To enable this in nodepool, you'll use the node-attributes setting in a
      provider pool. For example:

      .. code-block:: yaml

        pools:
          - name: main
            node-attributes:
              executor-zone: vpn

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

In order to stop the executor and under normal circumstances it is
best to pause and wait for all currently running jobs to finish
before stopping it. To do so run ``zuul-executor pause``.

To stop the executor immediately, run ``zuul-executor stop``. Jobs that were
running on the stopped executor will be rescheduled on other executors.

To enable or disable running Ansible in verbose mode (with the
``-vvv`` argument to ansible-playbook) run ``zuul-executor verbose``
and ``zuul-executor unverbose``.

Web Server
----------

.. TODO: Turn REST API into a link to swagger docs when we grow them

The Zuul web server serves as the single process handling all HTTP
interactions with Zuul. This includes the websocket interface for live
log streaming, the REST API and the html/javascript dashboard. All three are
served as a holistic web application. For information on additional supported
deployment schemes, see :ref:`web-deployment-options`.

Web servers need to be able to connect to the Gearman server (usually
the scheduler host).  If the SQL reporter is used, they need to be
able to connect to the database it reports to in order to support the
dashboard.  If a GitHub connection is configured, they need to be
reachable by GitHub so they may receive notifications.

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
      :default: /var/run/zuul/web.pid

      Path to PID lock file for the web server process.

   .. attr:: port
      :default: 9000

      Port to use for web server process.

   .. attr:: websocket_url

      Base URL on which the websocket service is exposed, if different
      than the base URL of the web app.

   .. attr:: stats_url

      Base URL from which statistics emitted via statsd can be queried.

   .. attr:: stats_type
      :default: graphite

      Type of server hosting the statistics information. Currently only
      'graphite' is supported by the dashboard.

   .. attr:: static_path
      :default: zuul/web/static

      Path containing the static web assets.

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

Finger gateway servers need to be able to connect to the Gearman
server (usually the scheduler host), as well as the console streaming
port on the executors (usually 7900).

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
      :default: /var/run/zuul/fingergw.pid

      Path to PID lock file for the finger gateway process.

   .. attr:: port
      :default: 79

      Port to use for the finger gateway. Note that since command line
      finger clients cannot usually specify the port, leaving this set to
      the default value is highly recommended.

   .. attr:: user

      User ID for the zuul-fingergw process. In normal operation as a
      daemon, the finger gateway should be started as the ``root``
      user, but if this option is set, it will drop privileges to this
      user during startup.  It is recommended to set this option to an
      unprivileged user.

Operation
~~~~~~~~~

To start the finger gateway, run ``zuul-fingergw``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.
