.. _glossary:

Glossary
========

.. glossary::
   :sorted:

   base job

      A job with no parent.  A base job may only be defined in a
      :term:`config-project`.  Multiple base jobs may be defined, but
      each tenant has a single default job which will be used as the
      parent of any job which does not specify one explicitly.

   check

      By convention, the name of a pipeline which performs pre-merge
      tests.  Such a pipeline might be triggered by creating a new
      change or pull request.  It may run with changes which have not
      yet seen any human review, so care must be taken in selecting
      the kinds of jobs to run, and what resources will be available
      to them in order to avoid misuse of the system or credential
      compromise.

   config-project

      One of two types of projects which may be specified by the
      administrator in the tenant config file.  A config-project is
      primarily tasked with holding configuration information and job
      content for Zuul.  Jobs which are defined in a config-project
      are run with elevated privileges, and all Zuul configuration
      items are available for use.  It is expected that changes to
      config-projects will undergo careful scrutiny before being
      merged.

   gate

      By convention, the name of a pipeline which performs project
      gating.  Such a pipeline might be triggered by a core team
      member approving a change or pull request.  It should have a
      :value:`dependent <pipeline.manager.dependent>` pipeline manager
      so that it can combine and sequence changes as they are
      approved.

   reporter

      A reporter is a :ref:`pipeline attribute <reporters>` which
      describes the action performed when an item is dequeued after
      its jobs complete.  Reporters are implemented by :ref:`drivers`
      so their actions may be quite varied.  For example, a reporter
      might leave feedback in a remote system on a proposed change,
      send email, or store information in a database.

   trusted execution context

      Playbooks defined in a :term:`config-project` run in the
      *trusted* execution context.  The trusted execution context has
      access to all Ansible features, including the ability to load
      custom Ansible modules.

   untrusted execution context

      Playbooks defined in an :term:`untrusted-project` run in the
      *untrusted* execution context.  Playbooks run in the untrusted
      execution context are not permitted to load additional Ansible
      modules or access files outside of the restricted environment
      prepared for them by the executor.  In addition to the
      bubblewrap environment applied to both execution contexts, in
      the untrusted context some standard Ansible modules are replaced
      with versions which prohibit some actions, including attempts to
      access files outside of the restricted execution context.  These
      redundant protections are made as part of a defense-in-depth
      strategy.

   untrusted-project

      One of two types of projects which may be specified by the
      administrator in the tenant config file.  An untrusted-project
      is one whose primary focus is not to operate Zuul, but rather it
      is one of the projects being tested or deployed.  The Zuul
      configuration language available to these projects is somewhat
      restricted, and jobs defined in these projects run in a
      restricted execution environment since they may be operating on
      changes which have not yet undergone review.
