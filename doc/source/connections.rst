:title: Connections

.. _connections:

Connections
===========

zuul coordinates talking to multiple different systems via the concept
of connections. A connection is listed in the :ref:`zuulconf` file and is
then referred to from the :ref:`layoutyaml`. This makes it possible to
receive events from gerrit via one connection and post results from another
connection that may report back as a different user.

Gerrit
------

Create a connection with gerrit.

**driver=gerrit**

**server**
  FQDN of Gerrit server.
  ``server=review.example.com``

**canonical_hostname**
  The canonical hostname associated with the git repos on the Gerrit
  server.  Defaults to the value of **server**.  This is used to
  identify repos from this connection by name and in preparing repos
  on the filesystem for use by jobs.
  ``canonical_hostname=git.example.com``

**port**
  Optional: Gerrit server port.
  ``port=29418``

**baseurl**
  Optional: path to Gerrit web interface. Defaults to ``https://<value
  of server>/``. ``baseurl=https://review.example.com/review_site/``

**user**
  User name to use when logging into above server via ssh.
  ``user=zuul``

**sshkey**
  Path to SSH key to use when logging into above server.
  ``sshkey=/home/zuul/.ssh/id_rsa``

**keepalive**
  Optional: Keepalive timeout, 0 means no keepalive.
  ``keepalive=60``

Gerrit Configuration
~~~~~~~~~~~~~~~~~~~~

Zuul will need access to a Gerrit user.

Create an SSH keypair for Zuul to use if there isn't one already, and
create a Gerrit user with that key::

  cat ~/id_rsa.pub | ssh -p29418 gerrit.example.com gerrit create-account --ssh-key - --full-name Jenkins jenkins

Give that user whatever permissions will be needed on the projects you
want Zuul to gate.  For instance, you may want to grant ``Verified
+/-1`` and ``Submit`` to the user.  Additional categories or values may
be added to Gerrit.  Zuul is very flexible and can take advantage of
those.

GitHub
------

Create a connection with GitHub.

**driver=github**

**api_token**
  API token for accessing GitHub.
  See `Creating an access token for command-line use
  <https://help.github.com/articles/creating-an-access-token-for-command-line-use/>`_.

**webhook_token**
  Optional: Token for validating the webhook event payloads.
  If not specified, payloads are not validated.
  See `Securing your webhooks
  <https://developer.github.com/webhooks/securing/>`_.

**sshkey**
  Path to SSH key to use when cloning github repositories.
  ``sshkey=/home/zuul/.ssh/id_rsa``

**git_host**
  Optional: Hostname of the github install (such as a GitHub Enterprise)
  If not specified, defaults to ``github.com``
  ``git_host=github.myenterprise.com``

SMTP
----

**driver=smtp**

**server**
  SMTP server hostname or address to use.
  ``server=localhost``

**port**
  Optional: SMTP server port.
  ``port=25``

**default_from**
  Who the email should appear to be sent from when emailing the report.
  This can be overridden by individual pipelines.
  ``default_from=zuul@example.com``

**default_to**
  Who the report should be emailed to by default.
  This can be overridden by individual pipelines.
  ``default_to=you@example.com``

SQL
----

  Only one connection per a database is permitted.

  **driver=sql**

  **dburi**
    Database connection information in the form of a URI understood by
    sqlalchemy. eg http://docs.sqlalchemy.org/en/rel_1_0/core/engines.html#database-urls
    ``dburi=mysql://user:pass@localhost/db``
