:title: SMTP Driver

SMTP
====

The SMTP driver supports reporters only.  It is used to send email
when items report.

Connection Configuration
------------------------

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

Reporter Configuration
----------------------

A simple email reporter is also available.

A :ref:`connection<connections>` that uses the smtp driver must be supplied to the
reporter.  The connection also may specify a default *To* or *From*
address.

Each pipeline can overwrite the ``subject`` or the ``to`` or ``from`` address by
providing alternatives as arguments to the reporter. For example, ::

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
