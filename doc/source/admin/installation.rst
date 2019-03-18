Installation Reference
======================

Install Zuul
------------

To install a Zuul release from PyPI, run::

    pip install zuul

Or from a git checkout, run::

    pip install .

That will also install Zuul's python dependencies.  To minimize
interaction with other python packages installed on a system, you may
wish to install Zuul within a Python virtualenv.

Zuul has several system-level dependencies as well.  You can find a
list of operating system packages in ``bindep.txt`` in Zuul's source
directory.

It is further required to run ``zuul-manage-ansible`` on the zuul-executor
in order to install all supported ansible versions so zuul can use them.

Zuul Components
---------------

Zuul provides the following components:

    - **zuul-scheduler**: The main Zuul process. Handles receiving
      events, executing jobs, collecting results and posting reports.
      Coordinates the work of the other components.  It also provides
      a gearman daemon which the other components use for
      coordination.

    - **zuul-merger**: Scale-out component that performs git merge
      operations.  Zuul performs a large number of git operations in
      the course of its work.  Adding merger processes can help speed
      Zuul's processing.  This component is optional (zero or more of
      these can be run).

    - **zuul-executor**: Scale-out component for executing jobs.  At
      least one of these is required.  Depending on system
      configuration, you can expect a single executor to handle up to
      about 100 simultaneous jobs.  Can handle the functions of a
      merger if dedicated mergers are not provided.  One or more of
      these must be run.

    - **zuul-web**: A web server that receives "webhook" events from
      external providers, supplies a web dashboard, and provides
      websocket access to live streaming of logs.

    - **zuul-fingergw**: A gateway which provides finger protocol
      access to live streaming of logs.

For more detailed information about these, see :ref:`components`.

External Dependencies
---------------------

Zuul interacts with several other systems described below.

Gearman
~~~~~~~

Gearman is a job distribution system that Zuul uses to communicate
with its distributed components.  The Zuul scheduler distributes work
to Zuul mergers and executors using Gearman.  You may supply your own
gearman server, but the Zuul scheduler includes a built-in server
which is recommended.  Ensure that all Zuul hosts can communicate with
the gearman server.

Zuul distributes secrets to executors via gearman, so be sure to
secure it with TLS and certificate authentication.  Obtain (or
generate) a certificate for both the server and the clients (they may
use the same certificate or have individual certificates).  They must
be signed by a CA, but it can be your own CA.

Nodepool
~~~~~~~~

In order to run all but the simplest jobs, Zuul uses a companion
program, Nodepool, to supply the nodes (whether dynamic cloud
instances or static hardware) used by jobs.  Before starting Zuul,
ensure you have Nodepool installed and any images you require built.
Zuul only makes one requirement of these nodes: that it be able to log
in given a username and ssh private key.

ZooKeeper
~~~~~~~~~

.. TODO: SpamapS any zookeeper config recommendations?

Nodepool uses ZooKeeper to communicate internally among its
components, and also to communicate with Zuul.  You can run a simple
single-node ZooKeeper instance, or a multi-node cluster.  Ensure that
the host running the Zuul scheduler has access to the cluster.

Ansible
~~~~~~~

Zuul uses Ansible to run jobs.  Each version of Zuul is designed to
work with a specific, contemporary versions of Ansible. Zuul manages
its Ansible installations using ``zuul-manage-ansible``. It is
recommended to run ``zuul-manage-ansible`` before starting the zuul-executor
the first time.

.. program-output:: zuul-manage-ansible -h


Zuul Setup
----------

At minimum you need to provide ``zuul.conf`` and ``main.yaml`` placed
in ``/etc/zuul/``.  The following example uses the builtin gearman
service in Zuul, and a connection to Gerrit.

**zuul.conf**::

    [scheduler]
    tenant_config=/etc/zuul/main.yaml

    [gearman_server]
    start=true

    [gearman]
    server=127.0.0.1

    [connection my_gerrit]
    driver=gerrit
    server=git.example.com
    port=29418
    baseurl=https://git.example.com/gerrit/
    user=zuul
    sshkey=/home/zuul/.ssh/id_rsa

See :ref:`components` and :ref:`connections` for more details.

The following tells Zuul to read its configuration from and operate on
the *example-project* project:

**main.yaml**::

    - tenant:
        name: example-tenant
        source:
          my_gerrit:
            untrusted-projects:
              - example-project

Starting Zuul
-------------

You can run any zuul process with the **-d** option to make it not
daemonize. It's a good idea at first to confirm there's no issues with
your configuration.

To start, simply run::

    zuul-scheduler

Once run you should have two zuul-scheduler processes (if using the
built-in gearman server, or one process otherwise).

Before Zuul can run any jobs, it needs to load its configuration, most
of which is in the git repositories that Zuul operates on.  Start an
executor to allow zuul to do that::

    zuul-executor

Zuul should now be able to read its configuration from the configured
repo and process any jobs defined therein.

.. _web-deployment-options:

Web Deployment Options
----------------------

The ``zuul-web`` service provides a web dashboard, a REST API and a websocket
log streaming service as a single holistic web application. For production use
it is recommended to run it behind a reverse proxy, such as Apache or Nginx.

The ``zuul-web`` service is entirely self-contained and can be run
with minimal configuration, however, more advanced users may desire to
do one or more of the following:

White Label
  Serve the dashboard of an individual tenant at the root of its own domain.
  https://zuul.openstack.org is an example of a Zuul dashboard that has been
  white labeled for the ``openstack`` tenant of its Zuul.

Static Offload
  Shift the duties of serving static files, such as HTML, Javascript, CSS or
  images to the reverse proxy server.

Static External
  Serve the static files from a completely separate location that does not
  support programmatic rewrite rules such as a Swift Object Store.

Sub-URL
  Serve a Zuul dashboard from a location below the root URL as part of
  presenting integration with other application.
  https://softwarefactory-project.io/zuul/ is an example of a Zuul dashboard
  that is being served from a Sub-URL.

Most deployments shouldn't need these, so the following discussion
will assume that the ``zuul-web`` service is exposed via a reverse
proxy. Where rewrite rule examples are given, they will be given with
Apache syntax, but any other reverse proxy should work just fine.

Reverse Proxy
~~~~~~~~~~~~~

Using Apache as the reverse proxy requires the ``mod_proxy``,
``mod_proxy_http`` and ``mod_proxy_wstunnel`` modules to be installed
and enabled.

All of the cases require a rewrite rule for the websocket streaming, so the
simplest reverse-proxy case is::

  RewriteEngine on
  RewriteRule ^/api/tenant/(.*)/console-stream ws://localhost:9000/api/tenant/$1/console-stream [P]
  RewriteRule ^/(.*)$ http://localhost:9000/$1 [P]

This is the recommended configuration unless one of the following
features is required.

Static Offload
~~~~~~~~~~~~~~

To have the reverse proxy serve the static html/javascript assets
instead of proxying them to the REST layer, enable the ``mod_rewrite``
Apache module, register the location where you unpacked the web
application as the document root and add rewrite rules::

  <Directory /usr/share/zuul>
    Require all granted
  </Directory>
  Alias / /usr/share/zuul/
  <Location />
    RewriteEngine on
    RewriteBase /
    # Rewrite api to the zuul-web endpoint
    RewriteRule api/tenant/(.*)/console-stream ws://localhost:9000/api/tenant/$1/console-stream [P,L]
    RewriteRule api/(.*)$ http://localhost:9000/api/$1 [P,L]
    # Backward compatible rewrite
    RewriteRule t/(.*)/(.*).html(.*) /t/$1/$2$3 [R=301,L,NE]

    # Don't rewrite files or directories
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule . /index.html [L]
  </Location>


Sub directory serving
~~~~~~~~~~~~~~~~~~~~~

The web application needs to be rebuilt to update the internal location of
the static files. Set the homepage setting in the package.json to an
absolute path or url. For example, to deploy the web interface through a
'/zuul/' sub directory:

.. note::

   The web dashboard source code and package.json are located in the ``web``
   directory. All the yarn commands need to be executed from the ``web``
   directory.

.. code-block:: bash

   sed -e 's#"homepage": "/"#"homepage": "/zuul/"#' -i package.json
   yarn build

Then assuming the web application is unpacked in /usr/share/zuul,
enable the ``mod_rewrite`` Apache module and add the following rewrite
rules::

  <Directory /usr/share/zuul>
    Require all granted
  </Directory>
  Alias /zuul /usr/share/zuul/
  <Location /zuul>
    RewriteEngine on
    RewriteBase /zuul
    # Rewrite api to the zuul-web endpoint
    RewriteRule api/tenant/(.*)/console-stream ws://localhost:9000/api/tenant/$1/console-stream [P,L]
    RewriteRule api/(.*)$ http://localhost:9000/api/$1 [P,L]
    # Backward compatible rewrite
    RewriteRule t/(.*)/(.*).html(.*) /t/$1/$2$3 [R=301,L,NE]

    # Don't rewrite files or directories
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule . /zuul/index.html [L]
  </Location>


White Labeled Tenant
~~~~~~~~~~~~~~~~~~~~

Running a white-labeled tenant is similar to the offload case, but adds a
rule to ensure connection webhooks don't try to get put into the tenant scope.

.. note::

   It's possible to do white-labeling without static offload, but it
   is more complex with no benefit.

Enable the ``mod_rewrite`` Apache module, and assuming the Zuul tenant
name is ``example``, the rewrite rules are::

  <Directory /usr/share/zuul>
    Require all granted
  </Directory>
  Alias / /usr/share/zuul/
  <Location />
    RewriteEngine on
    RewriteBase /
    # Rewrite api to the zuul-web endpoint
    RewriteRule api/connection/(.*)$ http://localhost:9000/api/connection/$1 [P,L]
    RewriteRule api/console-stream ws://localhost:9000/api/tenant/example/console-stream [P,L]
    RewriteRule api/(.*)$ http://localhost:9000/api/tenant/example/$1 [P,L]
    # Backward compatible rewrite
    RewriteRule t/(.*)/(.*).html(.*) /t/$1/$2$3 [R=301,L,NE]

    # Don't rewrite files or directories
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule . /index.html [L]
  </Location>



Static External
~~~~~~~~~~~~~~~

.. note::

   Hosting the Zuul dashboard on an external static location that does
   not support dynamic url rewrite rules only works for white-labeled
   deployments.

In order to serve the zuul dashboard code from an external static location,
``REACT_APP_ZUUL_API`` must be set at javascript build time:

.. code-block:: bash

   REACT_APP_ZUUL_API='http://zuul-web.example.com' yarn build
