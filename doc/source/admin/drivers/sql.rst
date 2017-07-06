:title: SQL Driver

SQL
===

The SQL driver supports reporters only.  Only one connection per
database is permitted.  The connection options are:

**driver=sql**

**dburi**
  Database connection information in the form of a URI understood by
  sqlalchemy. eg http://docs.sqlalchemy.org/en/rel_1_0/core/engines.html#database-urls
  ``dburi=mysql://user:pass@localhost/db``

Reporter Configuration
----------------------

This reporter is used to store results in a database.

A :ref:`connection<connections>` that uses the sql driver must be
supplied to the reporter.

zuul.conf contains the database connection and credentials. To store different
reports in different databases you'll need to create a new connection per
database.

The SQL reporter does nothing on "start" or "merge-failure"; it only
acts on "success" or "failure" reporting stages.

**score**
  A score to store for the result of the build. eg: -1 might indicate a failed
  build.

For example ::

  - pipeline:
      name: post-merge
      success:
        mydb_conn:
            score: 1
      failure:
        mydb_conn:
            score: -1
