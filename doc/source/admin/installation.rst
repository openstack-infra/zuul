Installation
============

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
list of operating system packages in `bindep.txt` in Zuul's source
directory.

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

.. TODO: SpamapS any zookeeper config recommendations?

Nodepool uses Zookeeper to communicate internally among its
components, and also to communicate with Zuul.  You can run a simple
single-node Zookeeper instance, or a multi-node cluster.  Ensure that
the host running the Zuul scheduler has access to the cluster.

Ansible
~~~~~~~

Zuul uses Ansible to run jobs.  Each version of Zuul is designed to
work with a specific, contemporary version of Ansible.  Zuul specifies
that version of Ansible in its python package metadata, and normally
the correct version will be installed automatically with Zuul.
Because of the close integration of Zuul and Ansible, attempting to
use other versions of Ansible with Zuul is not recommended.

.. _web-deployment-options:

Web Deployment Options
======================

The ``zuul-web`` service provides an web dashboard, a REST API and a websocket
log streaming service as a single holistic web application. For production use
it is recommended to run it behind a reverse proxy, such as Apache or Nginx.

More advanced users may desire to do one or more exciting things such as:

White Label
  Serve the dashboard of an individual tenant at the root of its own domain.
  https://zuul.openstack.org is an example of a Zuul dashboard that has been
  white labeled for the ``openstack`` tenant of its Zuul.

Static Offload
  Shift the duties of serving static files, such as HTML, Javascript, CSS or
  images to the Reverse Proxy server.

Static External
  Serve the static files from a completely separate location that does not
  support programmatic rewrite rules such as a Swift Object Store.

Sub-URL
  Serve a Zuul dashboard from a location below the root URL as part of
  presenting integration with other application.
  https://softwarefactory-project.io/zuul/ is an example of a Zuul dashboard
  that is being served from a Sub-URL.

None of those make any sense for simple non-production oriented deployments, so
all discussion will assume that the ``zuul-web`` service is exposed via a
Reverse Proxy. Where rewrite rule examples are given, they will be given
with Apache syntax, but any other Reverse Proxy should work just fine.

Basic Reverse Proxy
-------------------

Using Apache as the Reverse Proxy requires the ``mod_proxy``,
``mod_proxy_http`` and ``mod_proxy_wstunnel`` modules to be installed and
enabled. Static Offload and White Label additionally require ``mod_rewrite``.

All of the cases require a rewrite rule for the websocket streaming, so the
simplest reverse-proxy case is::

  RewriteEngine on
  RewriteRule ^/api/tenant/(.*)/console-stream ws://localhost:9000/api/tenant/$1/console-stream [P]
  RewriteRule ^/(.*)$ http://localhost:9000/$1 [P]


Static Offload
--------------

To have the Reverse Proxy serve the static html/javascript assets instead of
proxying them to the REST layer, register the location where you unpacked
the web application as the document root and add rewrite rules::

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
---------------------

The web application needs to be rebuild to update the internal location of
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
add the following rewrite rules::

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
--------------------

Running a white-labeled tenant is similar to the offload case, but adds a
rule to ensure connection webhooks don't try to get put into the tenant scope.

.. note::

  It's possible to do white-labelling without static offload, but it is more
  complex with no benefit.

Assuming the zuul tenant name is "example", the rewrite rules are::

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
---------------

.. note::

  Hosting zuul dashboard on an external static location that does not support
  dynamic url rewrite rules only works for white-labeled deployments.

In order to serve the zuul dashboard code from an external static location,
``REACT_APP_ZUUl_API`` must be set at javascript build time:

.. code-block:: bash

  REACT_APP_ZUUL_API='http://zuul-web.example.com' yarn build
