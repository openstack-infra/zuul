Zuul Dashboard Javascript
=========================

zuul-web has an html, css and javascript component, `zuul-dashboard`, that
is managed using Javascript toolchains. It is intended to be served by zuul-web
directly from zuul/web/static in the simple case, or to be published to
an alternate static web location, such as an Apache server.

The web dashboard is written in `Typescript`_ and `Angular`_ and is
managed by `yarn`_ and `webpack`_ which in turn both assume a functioning
and recent `nodejs`_ installation.

For the impatient who don't want deal with javascript toolchains
----------------------------------------------------------------

tl;dr - You have to build stuff with javascript tools.

The best thing would be to get familiar with the tools, there are a lot of
good features available. If you're going to hack on the Javascript, you should
get to know them.

If you don't want to hack on Javascript and just want to run Zuul's tests,
``tox`` has been set up to handle it for you.

If you do not have `yarn`_ installed, ``tox`` will use `nodeenv`_ to install
node into the active python virtualenv, and then will install `yarn`_ into
that virtualenv as well.

yarn dependency management
--------------------------

`yarn`_ manages the javascript dependencies. That means the first step is
getting `yarn`_ installed.

.. code-block:: console

  tools/install-js-tools.sh

The ``tools/install-js-tools.sh`` script will add apt or yum repositories and
install `nodejs`_ and `yarn`_ from them. For RPM-based distros it needs to know
which repo description file to download, so it calls out to
``tools/install-js-repos-rpm.sh``.

Once yarn is installed, getting dependencies installed is:

.. code-block:: console

  yarn install

The ``yarn.lock`` file contains all of the specific versions that were
installed before. Since this is an application it has been added to the repo.

To add new runtime dependencies:

.. code-block:: console

  yarn add awesome-package

To add new build-time dependencies:

.. code-block:: console

  yarn add -D awesome-package

To remove dependencies:

.. code-block:: console

  yarn remove terrible-package

Adding or removing packages will add the logical dependency to ``package.json``
and will record the version of the package and any of its dependencies that
were installed into ``yarn.lock`` so that other users can simply run
``yarn install`` and get the same environment.

To update a dependency:

.. code-block:: console

  yarn add awesome-package

Dependencies are installed into the ``node_modules`` directory. Deleting that
directory and re-running ``yarn install`` should always be safe.

Dealing with yarn.lock merge conflicts
--------------------------------------

Since ``yarn.lock`` is generated, it can create merge conflicts. Resolving
them at the ``yarn.lock`` level is too hard, but `yarn`_ itself is
deterministic. The best procedure for dealing with ``yarn.lock`` merge
conflicts is to first resolve the conflicts, if any, in ``package.json``. Then:

.. code-block:: console

  yarn install --force
  git add yarn.lock

Which causes yarn to discard the ``yarn.lock`` file, recalculate the
dependencies and write new content.

webpack asset management
------------------------

`webpack`_ takes care of bundling web assets for deployment, including tasks
such as minifying and transpiling for older browsers. It takes a
javascript-first approach, and generates a html file that includes the
appropriate javascript and CSS to get going.

The main `webpack`_ config file is ``webpack.config.js``. In the Zuul tree that
file is a stub file that includes either a dev or a prod environment from
``web/config/webpack.dev.js`` or ``web/config/webpack.prod.js``. Most of the
important bits are in ``web/config/webpack.common.js``.

Angular Components
------------------

Each page has an `Angular Component`_ associated with it. For instance, the
``status.html`` page has code in ``web/status/status.component.ts`` and the
relevant HTML can be found in ``web/status/status.component.html``.

Mapping of pages/urls to components can be found in the routing module in
``web/app-routing.module.ts``.

Development
-----------

Building the code can be done with:

.. code-block:: bash

  npm run build

zuul-web has a ``static`` route defined which serves files from
``zuul/web/static``. ``npm run build`` will put the build output files
into the ``zuul/web/static`` directory so that zuul-web can serve them.

There is a also a development-oriented version of that same command:

.. code-block:: bash

  npm run build:dev

which will build for the ``dev`` environment. This causes some sample data
to be bundled and included.

Webpack includes a development server that handles things like reloading and
hot-updating of code. The following:

.. code-block:: bash

  npm run start

will build the code and launch the dev server on `localhost:8080`. It will
be configured to use the API endpoint from OpenStack's Zuul. The
``webpack-dev-server`` watches for changes to the files and
re-compiles/refresh as needed.

.. code-block:: bash

  npm run start:multi

will do the same but will be pointed at the SoftwareFactory Project Zuul, which
is multi-tenant.

Arbitrary command line options will be passed through after a ``--`` such as:

.. code-block:: bash

  npm run start -- --open-file='status.html'

That's kind of annoying though, so additional targets exist for common tasks:

Run status against `basic` built-in demo data.

.. code-block:: bash

  npm run start:basic

Run status against `openstack` built-in demo data

.. code-block:: bash

  npm run start:openstack

Run status against `tree` built-in demo data.

.. code-block:: bash

  npm run start:tree

Additional run commands can be added in `package.json` in the ``scripts``
section.

Deploying
---------

The web application is a set of static files and is designed to be served
by zuul-web from its ``static`` route. In order to make sure this works
properly, the javascript build needs to be performed so that the javascript
files are in the ``zuul/web/static`` directory. Because the javascript
build outputs into the ``zuul/web/static`` directory, as long as
``npm run build`` has been done before ``pip install .`` or
``python setup.py sdist``, all the files will be where they need to be.
As long as `yarn`_ is installed, the installation of zuul will run
``npm run build`` appropriately.

Debugging minified code
-----------------------

Both the ``dev`` and ``prod`` ennvironments use the same `devtool`_
called ``source-map`` which makes debugging errors easier by including mapping
information from the minified and bundled resources to their approriate
non-minified source code locations. Javascript errors in the browser as seen
in the developer console can be clicked on and the appropriate actual source
code location will be shown.

``source-map`` is considered an appropriate `devtool`_ for production, but has
the downside that it is slower to update. However, since it includes the most
complete mapping information and doesn't impact execution performance, so in
our case we use it for both.

.. _yarn: https://yarnpkg.com/en/
.. _nodejs: https://nodejs.org/
.. _webpack: https://webpack.js.org/
.. _devtool: https://webpack.js.org/configuration/devtool/#devtool
.. _nodeenv: https://pypi.org/project/nodeenv
.. _Angular: https://angular.io
.. _Angular Component: https://angular.io/guide/architecture-components
.. _Typescript: https://www.typescriptlang.org/
