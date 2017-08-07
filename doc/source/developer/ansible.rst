Ansible Integration
===================

Zuul contains Ansible modules and plugins to control the execution of Ansible
Job content. These break down into two basic categories.

* Restricted Execution on Executors
* Build Log Support

Restricted Execution
--------------------

Zuul runs ``ansible-playbook`` on executors to run job content on nodes. While
the intent is that content is run on the remote nodes, Ansible is a flexible
system that allows delegating actions to ``localhost``, and also reading and
writing files. These actions can be desirable and necessary for actions such
as fetching log files or build artifacts, but could also be used as a vector
to attack the executor.

For that reason Zuul implements a set of Ansible action plugins and lookup
plugins that override and intercept task execution during untrusted playbook
execution to ensure local actions are not executed or that for operations that
are desirable to allow locally that they only interact with files in the zuul
work directory.

.. autoclass:: zuul.ansible.action.normal.ActionModule
   :members:

Build Log Support
-----------------

Zuul provides realtime build log streaming to end users so that users can
watch long-running jobs in progress. As jobs may be written that execute a
shell script that could run for a long time, additional effort is expended
to stream stdout and stderr of shell tasks as they happen rather than waiting
for the command to finish.

Zuul contains a modified version of the :ansible:module:`command`
that starts a log streaming daemon on the build node.

.. automodule:: zuul.ansible.library.command

All jobs run with the :py:mod:`zuul.ansible.callback.zuul_stream` callback
plugin enabled, which writes the build log to a file so that the
:py:class:`zuul.lib.log_streamer.LogStreamer` can provide the data on demand
over the finger protocol. Finally, :py:class:`zuul.web.LogStreamingHandler`
exposes that log stream over a websocket connection as part of
:py:class:`zuul.web.ZuulWeb`.

.. autoclass:: zuul.ansible.callback.zuul_stream.CallbackModule
   :members:

.. autoclass:: zuul.lib.log_streamer.LogStreamer
.. autoclass:: zuul.web.LogStreamingHandler
.. autoclass:: zuul.web.ZuulWeb

In addition to real-time streaming, Zuul also installs another callback module,
:py:mod:`zuul.ansible.callback.zuul_json.CallbackModule` that collects all
of the information about a given run into a json file which is written to the
work dir so that it can be published along with build logs. Since the streaming
log is by necessity a single text stream, choices have to be made for
readability about what data is shown and what is not shown. The json log file
is intended to allow for a richer more interactive set of data to be displayed
to the user.

.. autoclass:: zuul.ansible.callback.zuul_json.CallbackModule
