:title: MQTT Driver

MQTT
====

The MQTT driver supports reporters only. It is used to send MQTT
message when items report.

Message Schema
--------------

An MQTT report uses this schema:

.. attr:: <mqtt schema>

   .. attr:: action

      The reporter action name, e.g.: 'start', 'success', 'failure',
      'merge-failure', ...

   .. attr:: tenant

      The tenant name.

   .. attr:: pipeline

      The pipeline name.

   .. attr:: project

      The project name.

   .. attr:: branch

      The branch name.

   .. attr:: change_url

      The change url.

   .. attr:: message

      The report message.

   .. attr:: change

      The change number.

   .. attr:: patchset

      The patchset number.

   .. attr:: ref

      The change reference.

   .. attr:: zuul_ref

      The internal zuul change reference.

   .. attr:: buildset

      The buildset information.

      .. value:: uuid

      The buildset global uuid.

      .. attr:: builds

      The list of builds.

         .. attr:: job_name

            The job name.

         .. attr:: voting

            The job voting status.

         .. attr:: uuid

            The build uuid (not present in start report).

         .. attr:: execute_time

            The build execute time.

         .. attr:: start_time

            The build start time (not present in start report).

         .. attr:: end_time

            The build end time (not present in start report).

         .. attr:: log_url

            The build log url (not present in start report).

         .. attr:: result

            The build results (not present in start report).


Here is an example of a start message:

.. code-block:: javascript

  {
    'action': 'start',
    'tenant': 'openstack.org',
    'pipeline': 'check',
    'project': 'sf-jobs',
    'branch': 'master',
    'change_url': 'https://gerrit.example.com/r/3',
    'message': 'Starting check jobs.',
    'change': '3',
    'patchset': '1',
    "ref": "refs/changes/03/3/1",
    'zuul_ref': 'Zf8b3d7cd34f54cb396b488226589db8f'
    'buildset': {
      'uuid': 'f8b3d7cd34f54cb396b488226589db8f'
      'builds': [{
        'job_name': 'linters',
        'voting': True
      }],
    },
  }


Here is an example of a success message:

.. code-block:: javascript

  {
    'action': 'success',
    'tenant': 'openstack.org',
    'pipeline': 'check',
    'project': 'sf-jobs',
    'branch': 'master',
    'change_url': 'https://gerrit.example.com/r/3',
    'message': 'Build succeeded.',
    'change': '3',
    'patchset': '1',
    "ref": "refs/changes/03/3/1",
    'zuul_ref': 'Zf8b3d7cd34f54cb396b488226589db8f'
    'buildset': {
      'uuid': 'f8b3d7cd34f54cb396b488226589db8f'
      'builds': [{
        'job_name': 'linters',
        'voting': True
        'uuid': '16e3e55aca984c6c9a50cc3c5b21bb83',
        'start_time': 1524801179.8557224,
        'end_time': 1524801208.928095,
        'log_url': 'https://logs.example.com/logs/3/3/1/check/linters/16e3e55/',
        'result': 'SUCCESS',
      }],
    },
  }


Connection Configuration
------------------------

.. attr:: <mqtt connection>

   .. attr:: driver
      :required:

      .. value:: mqtt

         The connection must set ``driver=mqtt`` for MQTT connections.

   .. attr:: server
      :default: localhost

      MQTT server hostname or address to use.

   .. attr:: port
      :default: 1883

      MQTT server port.

   .. attr:: keepalive
      :default: 60

      Maximum period in seconds allowed between communications with the broker.

   .. attr:: user

      Set a username for optional broker authentication.

   .. attr:: password

      Set a password for optional broker authentication.

   .. attr:: ca_certs

      A string path to the Certificate Authority certificate files to enable
      TLS connection.

   .. attr:: certfile

      A strings pointing to the PEM encoded client certificate to
      enable client TLS based authentication. This option requires keyfile to
      be set too.

   .. attr:: keyfile

      A strings pointing to the PEM encoded client private keys to
      enable client TLS based authentication. This option requires certfile to
      be set too.

   .. attr:: ciphers

      A string specifying which encryption ciphers are allowable for this
      connection. More information in this
      `openssl doc <https://www.openssl.org/docs/manmaster/man1/ciphers.html>`_.


Reporter Configuration
----------------------

A :ref:`connection<connections>` that uses the mqtt driver must be supplied to the
reporter. Each pipeline must provide a topic name. For example:

.. code-block:: yaml

   - pipeline:
       name: check
       success:
         mqtt:
           topic: "{tenant}/zuul/{pipeline}/{project}/{branch}/{change}"
           qos: 2


.. attr:: pipeline.<reporter>.<mqtt>

   To report via MQTT message, the dictionaries passed to any of the pipeline
   :ref:`reporter<reporters>` support the following attributes:

   .. attr:: topic

      The MQTT topic to publish messages. The topic can be a format string that
      can use the following parameters: ``tenant``, ``pipeline``, ``project``,
      ``branch``, ``change``, ``patchset`` and ``ref``.
      MQTT topic can have hierarchy separated by ``/``, more details in this
      `doc <https://mosquitto.org/man/mqtt-7.html>`_

   .. attr:: qos
      :default: 0

      The quality of service level to use, it can be 0, 1 or 2. Read more in this
      `guide <https://www.hivemq.com/blog/mqtt-essentials-part-6-mqtt-quality-of-service-levels>`_
