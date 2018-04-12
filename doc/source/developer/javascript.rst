Zuul Web Javascript
===================

zuul-web has an html, css and javascript component, `zuul-dashboard`, that
is managed using Javascript toolchains. It is intended to be served by zuul-web
directly from zuul/web/static in the simple case, or to be published to
an alternate static web location, such as an Apache server.

The web applications are managed by `yarn`_ and `webpack`_ which in turn both
assume a functioning and recent `nodejs`_ installation.

For the impatient who don't want deal with javascript toolchains
----------------------------------------------------------------

tl;dr - You have to build stuff with javascript tools.

The best thing would be to get familiar with the tools, there are a lot of
good features available. But, if you don't want to know anything about the
Javascript toolchains a few helpers have been provided.

tox
~~~

If you do not have `yarn`_ installed, ``tox`` will use `nodeenv`_ to install
node into the active python virtualenv, and then will install `yarn`_ into
that virtualenv as well.

npm + docker
~~~~~~~~~~~~

.. We should remove the build:docker command. If you have npm, you can
   npm install yarn.

If you have npm and docker installed and don't want to install newer nodejs
or a bunch of javascript libraries, you can run:

.. code-block:: bash

  npm run build:docker

docker
~~~~~~

If you have docker but do not have npm or nodejs installed, you can build
the web app with:

.. code-block:: bash

  docker run -it --rm -v ${PWD}:/usr/src/app:z -w /usr/src/app node:alpine \
      npm run build:dist-with-depends

Both do the same thing. Both versions will result in the built files being
put into ``zuul/web/static``.

.. note:: Because the user inside of the Docker container is root, the files
          that it emits into zuul/web/static will be owned by root.

yarn dependency management
--------------------------

`yarn`_ manages the javascript dependencies. That means the first step is
getting `yarn`_ installed.

.. code-block:: bash

  tools/install-js-tools.sh

The ``tools/install-js-tools.sh`` script will add apt or yum repositories and
install `nodejs`_ and `yarn`_ from them. For RPM-based distros it needs to know
which repo description file to download, so it calls out to
``tools/install-js-repos-rpm.sh``.

Once yarn is installed, getting dependencies installed is:

.. code-block:: bash

  yarn install

The ``yarn.lock`` file contains all of the specific versions that were
installed before. Since this is an application it has been added to the repo.

To add new dependencies:

.. code-block:: bash

  yarn add awesome-package

To remove dependencies:

.. code-block:: bash

  yarn remove terrible-package

Adding or removing packages will add the logical dependency to ``package.json``
and will record the version of the package and any of its dependencies that
were installed into ``yarn.lock`` so that other users can simply run
``yarn install`` and get the same environment.

To update a dependency:

.. code-block:: bash

  yarn add awesome-package

Dependencies are installed into the ``node_modules`` directory. Deleting that
directory and re-running ``yarn install`` should always be safe.

webpack asset management
------------------------

`webpack`_ takes care of bundling web assets for deployment, including tasks
such as minifying and transpiling for older browsers. It takes a
javascript-first approach, and generates a html file that includes the
appropriate javascript and CSS to get going.

We need to modify the html generated for each of our pages, so there are
templates in ``web/templates``.

The main `webpack`_ config file is ``webpack.config.js``. In the Zuul tree that
file is a stub file that includes either a dev or a prod environment from
``web/config/webpack.dev.js`` or ``web/config/webpack.prod.js``. Most of the
important bits are in ``web/config/webpack.common.js``.

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
additionally watch for changes to the files and re-compile/refresh as needed.
Arbitrary command line options will be passed through after a ``--`` such as:

.. code-block:: bash

  npm run start -- --open-file='static/status.html'

That's kind of annoying though, so additional targets exist for common tasks:

Run status against `basic` built-in demo data.

.. code-block:: bash

  npm run start:status:basic

Run status against `openstack` built-in demo data

.. code-block:: bash

  npm run start:status:openstack

Run status against `tree` built-in demo data.

.. code-block:: bash

  npm run start:status:tree

Run status against live data from OpenStack's Zuul.

.. code-block:: bash

  npm run start:status

Run builds against live data from OpenStack's Zuul.

.. code-block:: bash

  npm run start:builds

Run jobs against live data from OpenStack's Zuul.

.. code-block:: bash

  npm run start:jobs

Run console streamer.

.. note:: There is not currently a good way to pass build_id paramter.

.. code-block:: bash

  npm run start:stream

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
.. _nodeenv: https://pypi.python.org/pypi/nodeenv
