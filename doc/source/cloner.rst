:title: Zuul Cloner

Zuul Cloner
===========

Zuul includes a simple command line client that may be used to clone
repositories with Zuul references applied.

Configuration
-------------

Clone map
'''''''''

By default, Zuul cloner will clone the project under ``basepath`` which
would create sub directories whenever a project name contains slashes.  Since
you might want to finely tweak the final destination, a clone map lets you
change the destination on a per project basis.  The configuration is done using
a YAML file passed with ``-m``.

With a project hierarchy such as::

 project
 thirdparty/plugins/plugin1

You might want to get ``project`` straight in the base path, the clone map would be::

  clonemap:
   - name: 'project'
     dest: '.'

Then to strip out ``thirdparty`` such that the plugins land under the
``/plugins`` directory of the basepath, you can use regex and capturing
groups::

  clonemap:
   - name: 'project'
     dest: '.'
   - name: 'thirdparty/(plugins/.*)'
     dest: '\1'

The resulting workspace will contains::

  project -> ./
  thirdparty/plugins/plugin1  -> ./plugins/plugin1


Zuul parameters
'''''''''''''''

The Zuul cloner reuses Zuul parameters such as ZUUL_BRANCH, ZUUL_REF or
ZUUL_PROJECT.  It will attempt to load them from the environment variables or
you can pass them as parameters (in which case it will override the
environment variable if it is set).  The matching command line parameters use
the ``zuul`` prefix hence ZUUL_REF can be passed to the cloner using
``--zuul-ref``.

Usage
-----
The general options that apply are:

.. program-output:: zuul-cloner --help

Clone order
-----------

When cloning repositories, the destination folder should not exist or
``git clone`` will complain. This happens whenever cloning a sub project
before its parent project. For example::

 zuul-cloner project/plugins/plugin1 project

Will create the directory ``project`` when cloning the plugin. The
cloner processes the clones in the order supplied, so you should swap the
projects::

  zuul-cloner project project/plugins/plugin1

Cached repositories
-------------------

The ``--cache-dir`` option can be used to reduce network traffic by
cloning from a local repository which may not be up to date.

If the ``--cache-dir`` option is supplied, zuul-cloner will start by
cloning any projects it processes from those found in that directory.
The URL of origin remote of the resulting clone will be reset to use
the ``git_base_url`` and then the remote will be updated so that the
repository has all the information in the upstream repository.
