:title: SQL Driver

SQL
===

The SQL driver supports reporters only.  Only one connection per
database is permitted.

Connection Configuration
------------------------

The connection options for the SQL driver are:

.. attr:: <sql connection>

   .. attr:: driver
      :required:

      .. value:: sql

         The connection must set ``driver=sql`` for SQL connections.

   .. attr:: dburi
      :required:

      Database connection information in the form of a URI understood
      by SQLAlchemy.  See `The SQLAlchemy manual
      <https://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls>`_
      for more information.

      The driver will automatically set up the database creating and managing
      the necessary tables. Therefore the provided user should have sufficient
      permissions to manage the database. For example:

      .. code-block:: sql

        GRANT ALL ON my_database TO 'my_user'@'%';

   .. attr:: pool_recycle
      :default: 1

      Tune the pool_recycle value. See `The SQLAlchemy manual on pooling
      <http://docs.sqlalchemy.org/en/latest/core/pooling.html#setting-pool-recycle>`_
      for more information.

   .. attr:: table_prefix
      :default: ''

      The string to prefix the table names. This makes it possible to run
      several zuul deployments against the same database. This can be useful
      if you rely on external databases which you don't have under control.
      The default is to have no prefix.

Reporter Configuration
----------------------

This reporter is used to store results in a database.

A :ref:`connection<connections>` that uses the sql driver must be
supplied to the reporter.

``zuul.conf`` contains the database connection and credentials. To
store different reports in different databases you'll need to create a
new connection per database.

The SQL reporter does nothing on :attr:`pipeline.start` or
:attr:`pipeline.merge-failure`; it only acts on
:attr:`pipeline.success` or :attr:`pipeline.failure` reporting stages.

For example:

.. code-block:: yaml

   - pipeline:
       name: post-merge
       success:
         mydb_conn:
       failure:
         mydb_conn:

.. attr:: pipeline.<reporter>.<sql source>

   To report to a database, add a key with the connection name and an
   empty value to the desired pipeline :ref:`reporter<reporters>`
   attributes.
