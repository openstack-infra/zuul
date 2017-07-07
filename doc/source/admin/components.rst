:title: Components

.. _components:

Components
==========

Zuul is a distributed system consisting of several components, each of
which is described below.  All Zuul processes read the
**/etc/zuul/zuul.conf** file (an alternate location may be supplied on
the command line) which uses an INI file syntax.  Each component may
have its own configuration file, though you may find it simpler to use
the same file for all components.

A minimal Zuul system may consist of a *scheduler* and *executor* both
running on the same host.  Larger installations should consider
running multiple executors, each on a dedicated host, and running
mergers on dedicated hosts as well.

Common
------

The following applies to all Zuul components.

Configuration
~~~~~~~~~~~~~

The following sections of **zuul.conf** are used by all Zuul components:

gearman
"""""""

Client connection information for gearman.

**server** (required)
  Hostname or IP address of the Gearman server::

     server=gearman.example.com

**port**
  Port on which the Gearman server is listening::

     port=4730

**ssl_ca**
  An openssl file containing a set of concatenated “certification
  authority” certificates in PEM formet.

**ssl_cert**
  An openssl file containing the client public certificate in PEM format.

**ssl_key**
  An openssl file containing the client private key in PEM format.

zookeeper
"""""""""

.. NOTE: this is a white lie at this point, since only the scheduler
   uses this, however, we expect other components to use it later, so
   it's reasonable for admins to plan for this now.

**hosts**
  A list of zookeeper hosts for Zuul to use when communicating with
  Nodepool::

     hosts=zk1.example.com,zk2.example.com,zk3.example.com


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

The following sections of **zuul.conf** are used by the scheduler:

gearman_server
""""""""""""""

The builtin gearman server. Zuul can fork a gearman process from itself rather
than connecting to an external one.

**start**
  Whether to start the internal Gearman server (default: False)::

     start=true

**listen_address**
  IP address or domain name on which to listen (default: all addresses)::

     listen_address=127.0.0.1

**log_config**
  Path to log config file for internal Gearman server::

     log_config=/etc/zuul/gearman-logging.yaml

**ssl_ca**
  An openssl file containing a set of concatenated “certification authority”
  certificates in PEM formet.

**ssl_cert**
  An openssl file containing the server public certificate in PEM format.

**ssl_key**
  An openssl file containing the server private key in PEM format.

webapp
""""""

**listen_address**
  IP address or domain name on which to listen (default: 0.0.0.0)::

     listen_address=127.0.0.1

**port**
  Port on which the webapp is listening (default: 8001)::

     port=8008

**status_expiry**
  Zuul will cache the status.json file for this many seconds (default: 1)::

     status_expiry=1

**status_url**
  URL that will be posted in Zuul comments made to changes when
  starting jobs for a change.  Used by zuul-scheduler only::

     status_url=https://zuul.example.com/status

scheduler
"""""""""

**tenant_config**
  Path to tenant config file::

     layout_config=/etc/zuul/tenant.yaml

**log_config**
  Path to log config file::

     log_config=/etc/zuul/scheduler-logging.yaml

**pidfile**
  Path to PID lock file::

     pidfile=/var/run/zuul/scheduler.pid

**state_dir**
  Path to directory that Zuul should save state to::

     state_dir=/var/lib/zuul

Operation
~~~~~~~~~

To start the scheduler, run ``zuul-scheduler``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

Most of Zuul's configuration is automatically updated as changes to
the repositories which contain it are merged.  However, Zuul must be
explicitly notified of changes to the tenant config file, since it is
not read from a git repository.  To do so, send the scheduler PID
(saved in the pidfile specified in the configuration) a SIGHUP signal.

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

The following section of **zuul.conf** is used by the merger:

merger
""""""

**git_dir**
  Directory that Zuul should clone local git repositories to::

     git_dir=/var/lib/zuul/git

**git_user_email**
  Value to pass to `git config user.email`::

     git_user_email=zuul@example.com

**git_user_name**
  Value to pass to `git config user.name`::

     git_user_name=zuul

**log_config**
  Path to log config file for the merger process::

     log_config=/etc/zuul/logging.yaml

**pidfile**
  Path to PID lock file for the merger process::

     pidfile=/var/run/zuul-merger/merger.pid

Operation
~~~~~~~~~

To start the merger, run ``zuul-merger``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.

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
on whether the project containing the playbook is a *config project*
or an *untrusted project*.  If the playbook is in a *config project*,
the executor runs the playbook in the *trusted* execution context,
otherwise, it is run in the *untrusted* execution context.

Both execution contexts use `bubblewrap`_ to create a namespace to
ensure that playbook executions are isolated and are unable to access
files outside of a restricted environment.  The administrator may
configure additional local directories on the executor to be made
available to the restricted environment.

The *trusted* execution context has access to all Ansible features,
including the ability to load custom Ansible modules.  Needless to
say, extra scrutiny should be given to code that runs in a trusted
context as it could be used to compromise other jobs running on the
executor, or the executor itself, especially if the administrator has
granted additional access through bubblewrap, or a method of escaping
the restricted environment created by bubblewrap is found.

Playbooks run in the *untrusted* execution context are not permitted
to load additional Ansible modules or access files outside of the
restricted environment prepared for them by the executor.  In addition
to the bubblewrap environment applied to both execution contexts, in
the *untrusted* context some standard Ansible modules are replaced
with versions which prohibit some actions, including attempts to
access files outside of the restricted execution context.  These
redundant protections are made as part of a defense-in-depth strategy.

.. _bubblewrap: https://github.com/projectatomic/bubblewrap

Configuration
~~~~~~~~~~~~~

The following sections of **zuul.conf** are used by the executor:

executor
""""""""

**finger_port**
  Port to use for finger log streamer::

     finger_port=79

**git_dir**
  Directory that Zuul should clone local git repositories to::

     git_dir=/var/lib/zuul/git

**log_config**
  Path to log config file for the executor process::

     log_config=/etc/zuul/logging.yaml

**private_key_file**
  SSH private key file to be used when logging into worker nodes::

     private_key_file=~/.ssh/id_rsa

**user**
  User ID for the zuul-executor process. In normal operation as a daemon,
  the executor should be started as the ``root`` user, but it will drop
  privileges to this user during startup::

     user=zuul

merger
""""""

**git_user_email**
  Value to pass to `git config user.email`::

     git_user_email=zuul@example.com

**git_user_name**
  Value to pass to `git config user.name`::

     git_user_name=zuul

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

To enable or disable running Ansible in verbose mode (with the '-vvv'
argument to ansible-playbook) run ``zuul-executor verbose`` and
``zuul-executor unverbose``.

Web Server
----------

The Zuul web server currently acts as a websocket interface to live log
streaming. Eventually, it will serve as the single process handling all
HTTP interactions with Zuul.

Configuration
~~~~~~~~~~~~~

In addition to the ``gearman`` common configuration section, the following
sections of **zuul.conf** are used by the web server:

web
"""

**listen_address**
  IP address or domain name on which to listen (default: 127.0.0.1)::

     listen_address=127.0.0.1

**log_config**
  Path to log config file for the web server process::

     log_config=/etc/zuul/logging.yaml

**pidfile**
  Path to PID lock file for the web server process::

     pidfile=/var/run/zuul-web/zuul-web.pid

**port**
  Port to use for web server process::

     port=9000

**websocket_url**
  Base URL on which the websocket service is exposed, if different than the
  base URL of the web app.

Operation
~~~~~~~~~

To start the web server, run ``zuul-web``.  To stop it, kill the
PID which was saved in the pidfile specified in the configuration.
