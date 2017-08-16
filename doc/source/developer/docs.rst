Documentation
=============

This is a brief style guide for Zuul documentation.

ReStructuredText Conventions
----------------------------

Code Blocks
~~~~~~~~~~~

When showing a YAML example, use the ``.. code-block:: yaml``
directive so that the sample appears as a code block with the correct
syntax highlighting.

Literal Values
~~~~~~~~~~~~~~

Filenames and literal values (such as when we instruct a user to type
a specific string into a configuration file) should use the RST
````literal```` syntax.

YAML supports boolean values expressed with or without an initial
capital letter.  In examples and documentation, use ``true`` and
``false`` in lowercase type because the resulting YAML is easier for
users to type and read.

Terminology
~~~~~~~~~~~

Zuul employs some specialized terminology.  To help users become
acquainted with it, we employ a glossary.  Observe the following:

* Specialized terms should have entries in the glossary.

* If the term is being defined in the text, don't link to the glossary
  (that would be redundant), but do emphasize it with ``*italics*``
  the first time it appears in that definition.  Subsequent uses
  within the same subsection should be in regular type.

* If it's being used (but not defined) in the text, link the first
  usage within a subsection to the glossary using the ``:term:`` role,
  but subsequent uses should be in regular type.

* Be cognizant of how readers may jump to link targets within the
  text, so be liberal in considering that once you cross a link
  target, you may be in a new "subsection" for the above guideline.


Zuul Sphinx Directives
----------------------

The following extra Sphinx directives are available in the ``zuul``
domain.  The ``zuul`` domain is configured as the default domain, so the
``zuul:`` prefix may be omitted.

zuul:attr::
~~~~~~~~~~~

This should be used when documenting Zuul configuration attributes.
Zuul configuration is heavily hierarchical, and this directive
facilitates documenting these by emphasising the hierarchy as
appropriate.  It will annotate each configuration attribute with a
nice header with its own unique hyperlink target.  It displays the
entire hierarchy of the attribute, but emphasises the last portion
(i.e., the field being documented).

To use the hierarchical features, simply nest with indentation in the
normal RST manner.

It supports the ``required`` and ``default`` options and will annotate
the header appropriately.  Example:

.. code-block:: rst

   .. attr:: foo

      Some text about ``foo``.

      .. attr:: bar
         :required:
         :default: 42

         Text about ``foo.bar``.

.. attr:: foo
   :noindex:

   Some text about ``foo``.

   .. attr:: bar
      :noindex:
      :required:
      :default: 42

      Text about ``foo.bar``.

zuul:value::
~~~~~~~~~~~~

Similar to zuul:attr, but used when documenting a literal value of an
attribute.

.. code-block:: rst

   .. attr:: foo

      Some text about foo.  It supports the following values:

      .. value:: bar

         One of the supported values for ``foo`` is ``bar``.

      .. value:: baz

         Another supported values for ``foo`` is ``baz``.

.. attr:: foo
   :noindex:

   Some text about foo.  It supports the following values:

   .. value:: bar
      :noindex:

      One of the supported values for ``foo`` is ``bar``.

   .. value:: baz
      :noindex:

      Another supported values for ``foo`` is ``baz``.

zuul:var::
~~~~~~~~~~

Also similar to zuul:attr, but used when documenting an Ansible
variable which is available to a job's playbook.  In these cases, it's
often necessary to indicate the variable may be an element of a list
or dictionary, so this directive supports a ``type`` option.  It also
supports the ``hidden`` option so that complex data structure
definitions may continue across sections.  To use this, set the hidden
option on a ``zuul:var::`` directive with the root of the data
structure as the name.  Example:

.. code-block:: rst

   .. var:: foo

      Foo is a dictionary with the following keys:

      .. var:: items
         :type: list

         Items is a list of dictionaries with the following keys:

         .. var:: bar

            Text about bar

   Section Boundary

   .. var:: foo
      :hidden:

      .. var:: baz

         Text about baz

.. End of code block; start example

.. var:: foo
   :noindex:

   Foo is a dictionary with the following keys:

   .. var:: items
      :noindex:
      :type: list

      Items is a list of dictionaries with the following keys:

      .. var:: bar
         :noindex:

         Text about bar

Section Boundary

.. var:: foo
   :noindex:
   :hidden:

   .. var:: baz
      :noindex:

      Text about baz

.. End of example

Zuul Sphinx Roles
-----------------

The following extra Sphinx roles are available.  Use these within the
text when referring to attributes, values, and variables defined with
the directives above.  Use these roles for the first appearance of an
object within a subsection, but use the ````literal```` role in
subsequent uses.

:zuul:attr:
~~~~~~~~~~~

This creates a reference to the named attribute.  Provide the fully
qualified name (e.g., ``:attr:`pipeline.manager```)

:zuul:value:
~~~~~~~~~~~~

This creates a reference to the named value.  Provide the fully
qualified name (e.g., ``:attr:`pipeline.manager.dependent```)

:zuul:var:
~~~~~~~~~~

This creates a reference to the named variable.  Provide the fully
qualified name (e.g., ``:var:`zuul.executor.name```)
