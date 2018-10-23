:title: SMTP Driver

SMTP
====

The SMTP driver supports reporters only.  It is used to send email
when items report.

Connection Configuration
------------------------

.. attr:: <smtp connection>

   .. attr:: driver
      :required:

      .. value:: smtp

         The connection must set ``driver=smtp`` for SMTP connections.

   .. attr:: server
      :default: localhost

      SMTP server hostname or address to use.

   .. attr:: port
      :default: 25

      SMTP server port.

   .. attr:: default_from
      :default: zuul

      Who the email should appear to be sent from when emailing the report.
      This can be overridden by individual pipelines.

   .. attr:: default_to
      :default: zuul

      Who the report should be emailed to by default.
      This can be overridden by individual pipelines.

   .. attr:: user

      Optional user name used to authenticate to the SMTP server. Used only in
      conjunction with a password. If no password is present, this option is
      ignored.

   .. attr:: password

      Optional password used to authenticate to the SMTP server.

   .. attr:: use_starttls
      :default: false

      Issue a STARTTLS request to establish an encrypted channel after having
      connected to the SMTP server.

Reporter Configuration
----------------------

A simple email reporter is also available.

A :ref:`connection<connections>` that uses the smtp driver must be supplied to the
reporter.  The connection also may specify a default *To* or *From*
address.

Each pipeline can overwrite the ``subject`` or the ``to`` or ``from`` address by
providing alternatives as arguments to the reporter. For example:

.. code-block:: yaml

   - pipeline:
       name: post-merge
       success:
         outgoing_smtp:
           to: you@example.com
       failure:
         internal_smtp:
           to: you@example.com
           from: alternative@example.com
           subject: Change {change} failed

.. attr:: pipeline.<reporter>.<smtp source>

   To report via email, the dictionaries passed to any of the pipeline
   :ref:`reporter<reporters>` attributes support the following
   attributes:

   .. attr:: to

      The SMTP recipient address for the report.  Multiple addresses
      may be specified as one value separated by commas.

   .. attr:: from

      The SMTP sender address for the report.

   .. attr:: subject

      The Subject of the report email.

      .. TODO: document subject string formatting.
