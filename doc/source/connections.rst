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
