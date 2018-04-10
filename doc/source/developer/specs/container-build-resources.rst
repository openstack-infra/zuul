Use Kubernetes for Build Resources
==================================

.. warning:: This is not authoritative documentation.  These features
   are not currently available in Zuul.  They may change significantly
   before final implementation, or may never be fully completed.

There has been a lot of interest in using containers for build
resources in Zuul.  The use cases are varied, so we need to describe
in concrete terms what we aim to support.  Zuul provides a number of
unique facilities to a CI/CD system which are well-explored in the
full-system context (i.e., VMs or bare metal) but it's less obvious
how to take advantage of these features in a container environment.
As we design support for containers it's also important that we
understand how things like speculative git repo states and job content
will work with containers.

In this document, we will consider two general approaches to using
containers as build resources:

* Containers that behave like a machine
* Native container workflow

Finally, there are multiple container environments.  Kubernetes and
OpenShift (an open source distribution of Kubernetes) are popular
environments which provide significant infrastructure to help us more
easily integrate them with Zuul, so this document will focus on these.
We may be able to extend this to other environments in the future.

.. _container-machine:

Containers That Behave Like a Machine
-------------------------------------

In some cases users may want to run scripted job content in an
environment that is more lightweight than a VM.  In this case, we're
expecting to get a container which behaves like a VM.  The important
characteristic of this scenario is that the job is not designed
specifically as a container-specific workload (e.g., it might simply
be a code style check).  It could just as easily run on a VM as a
container.

To achieve this, we should expect that a job defined in terms of
simple commands should work.  For example, a job which runs a playbook
with::

  hosts: all
  tasks:
    - command: tox -e pep8

Should work given an appropriate base job which prepares a container.

A user might expect to request a container in the same way they
request any other node::

  nodeset:
    nodes:
      - name: controller
        label: python-container

To provide this support, Nodepool would need to create the requested
container.  Nodepool can use either the kubernetes python client or
the `openshift python client`_ to do this.  The openshift client is
downstream of the native `kubernetes python client`_, so they are
compatible, but using the openshift client offers a superset of
functionality, which may come in handy later.  Since the Ansible
k8s_raw module uses the openshift client for this reason, we may want
to as well.

In kubernetes, a group of related containers forms a pod, which is the
API-level object used in order to cause a container or containers to
be created.  Even if a single container is desired, a pod with a
single container is created.  Therefore, for this case, Nodepool will
need to create a pod with a container.  Some aspects of the
container's configuration (such as the image which is used) will need
to be defined in the Nodepool configuration for the label.  These
configuration values should be supplied in a manner typical of
Nodepool's configuration format.  Note that very little customization
is expected here -- more complex topologies should not be supported by
this mechanism and should be left instead for :ref:`container-native`.

Containers in Kubernetes always run a single command, and when that
command is finished, the container terminates.  Nodepool doesn't have
the context to run a command at this point, so instead, it can create
a container running a command that can simply run forever, for
example, ``/bin/sh``.

A "container behaving like a machine" may be accessible via SSH, or it
may not.  It's generally not difficult to run an SSHD in a container,
however, in order for that to be useful, it still needs to be
accessible over the network from the Zuul executor.  This requires
that a service be configured for the container along with ingress
access to the cluster.  This is an additional complication that some
users may not want to undertake, especially if the goal is to run a
relatively simple job.  On the other hand, some environments may be
more natually suited to using an SSH connection.

We can address both cases, but they will be handled a bit differently.
First, the case where the container does run SSHD:

Nodepool would need to create a Kubernetes service for the container.
If Nodepool and the Zuul executor are running in the same Kubernetes
cluster, the container will be accessible to them, so Nodepool can
return this information to Zuul and the service address can be added
to the Ansible inventory with the SSH connection plugin as normal.  If
the kubernetes cluster is external to Nodepool and Zuul, Nodepool will
also need to establish an ingress resource in order to make it
externally accessible.  Both of these will require additional Nodepool
configuration and code to implement.  Due to the additional
complexity, these should be implemented as follow-on changes after the
simpler case where SSHD is not running in the container.

In the case where the container does not run SSHD, and we interact
with it via native commands, Nodepool will create a service account in
Kubernetes, and inform Zuul that the appropriate connection plugin for
Ansible is the `kubectl connection plugin`_, along with the service
account credentials, and Zuul will add it to the inventory with that
configuration.  It will then be able to run additional commands in the
container -- the commands which comprise the actual job.

Strictly speaking, this is all that is required for basic support in
Zuul, but as discussed in the introduction, we need to understand how
to build a complete solution including dealing with the speculative
git repo state.

A base job can be constructed to update the git repos inside the
container, and retrieve any artifacts produced.  We should be able to
have the same base job detect whether there are containers in the
inventory and alter behavior as needed to accomodate them.  For a
discussion of how the git repo state can be synchronised, see
:ref:`git-repo-sync`.

If we want streaming output from a kubectl command, we may need to
create a local fork of the kubectl connection plugin in order to
connect it to the log streamer (much in the way we do for the command
module).

Not all jobs will be expected to work in containers.  Some frequently
used Ansible modules will not behave as expected when run with the
kubectl connection plugin.  Synchronize, in particular, may be
problematic (though as there is support for synchronize with docker,
that may be possible to overcome).  We will want to think about
ways to keep the base job(s) as flexible as possible so they work with
multiple connection types, but there may be limits.  Containers which
run SSHD should not have these problems.

.. _kubectl connection plugin: https://docs.ansible.com/ansible/2.5/plugins/connection/kubectl.html
.. _openshift python client: https://pypi.org/project/openshift/
.. _kubernetes python client: https://pypi.org/project/kubernetes/

.. _container-native:

Native Container Workflow
-------------------------

A workflow that is designed from the start for containers may behave
very differently.  In particular, it's likely to be heavily image
based, and may have any number of containers which may be created and
destroyed in the process of executing the job.

It may use the `k8s_raw Ansible module`_ to interact directly with
Kubernetes, creating and destroying pods for the job in much the same
way that an existing job may use Ansible to orchestrate actions on a
worker node.

All of this means that we should not expect Nodepool to provide a
running container -- the job itself will create containers as needed.
It also means that we need to think about how a job will use the
speculative git repos.  It's very likely to need to build custom
images using those repos which are then used to launch containers.

Let's consider a job which begins by building container images from
the speculative git source, then launches containers from those images
and exercises them.

.. note:: It's also worth considering a complete job graph where a
   dedicated job builds images and subsequent jobs use them.  We'll
   deal with that situation in :ref:`buildset`.

Within a single job, we could build images by requesting either a full
machine or a :ref:`container-machine` from Nodepool and running the
image build on that machine.  Or we could use the `k8s_raw Ansible
module`_ to create that container from within the job.  We would use the
:ref:`git-repo-sync` process to get the appropriate source code onto
the builder.  Regardless, once the image builds are complete, we can
then use the result in the remainder of the job.

In order to use an image (regardless of how it's created) Kubernetes
is going to expect to be able to find the image in a repository it
knows about.  Putting images created based on speculative future git
repo stats into a public image repository may be confusing, and
require extra work to clean those up.  Therefore, the best approach
may be to work with private, per-build image repositories.

The best approach for this may be to have the job run an image
repository after it completes the image builds, then upload those
builds to the repository.  The only thing Nodepool needs to provide in
this situation is a Kubernetes namespace for the job.  The job itself
can perform the image build, create a service account token for the
image repository, run the image repository, and upload the image.  Of
course, it will be useful to create reusable roles and jobs in
zuul-jobs to implement this universally.

OpenShift provides some features that make this easier, so an
OpenShift-specific driver could additonally do the following and
reduce the complexity in the job:

We can ask Nodepool to create an `OpenShift project`_ for the use of
the job.  That will create a private image repository for the project.
Service accounts in the project are automatically created with
``imagePullSecrets`` configured to use the private image repository [#f1]_.
We can have Zuul use one of the default service accouns, or have
Nodepool create a new one specifically for Zuul, and then when using
the `k8s_raw Ansible module`_, the image registry will automatically be
used.

While we may consider expanding the Nodepool API and configuration
language to more explicitly support other types of resources in the
future, for now, the concept of labels is sufficiently generic to
support the use cases outlined here.  A label might correspond to a
virtual machine, physical machine, container, namespace, or OpenShift
project.  In all cases, Zuul requests one of these things from
Nodepool by using a label.

.. _OpenShift Project: https://docs.openshift.org/latest/dev_guide/projects.html
.. [#f1] https://docs.openshift.org/latest/dev_guide/managing_images.html#using-image-pull-secrets
.. _k8s_raw Ansible module: http://docs.ansible.com/ansible/2.5/modules/k8s_raw_module.html

.. _git-repo-sync:

Synchronizing Git Repos
-----------------------

Our existing method of synchronizing git repositories onto a worker
node relies on SSH.  It's possible to run an SSH daemon in a container
(or pod), but if it's otherwise not needed, it may be considered too
cumbersome.  In particular, it may mean establishing a service entry
in kubernetes and an ingress route so that the executor can reach the
SSH server.  However, it's always possible to run commands in a
container using kubectl with direct stdin/stdout connections without
any of the service/ingress complications.  It should be possible to
adapt our process to use this.

Our current process will use a git cache if present on the worker
image.  This is optional -- a Zuul user does not need a specially
prepared image, but if one is present, it can speed up operation.  In
a container environment, we could have Nodepool build container images
with a git repo cache, but in the world of containers, there are
universally accessible image stores, and considerable tooling around
building custom images already.  So for now, we won't have nodepool
build container images itself, but rather expect that a publicly
accessible base image will be used, or an administrator will create
and make an image available to Kubernetes if a custom image is needed
in their environment.  If we find that we also want to support
container image builds in Nodepool in the future, we can add support
for that later.

The first step in the process is to create a new pod based on either a
base image.  Ensure it has ``git`` installed.  If the pod is going to
be used to run a single command (i.e., :ref:`container-machine`, or
will only be used to build images), then a single container is
sufficient.  However, if the pod will support multiple containers,
each needing access to the git cache, then we can use the `sidecar
pattern`_ to update the git repo once.  In that case, in the pod
definition, we should specify an `emptyDir volume`_ where the final
git repos will be placed, and other containers in the pod can mount
the same volume.

Run commands in the container to clone the git repos to the
destination path.

Run commands in the container to push the updated git commits.  In
place of the normal ``git push`` command which relies on SSH, use a
custom SSH command which uses kubectl to set up the remote end of the
connection.

Here is an example custom ssh script:

.. code-block:: bash

   #!/bin/bash

   /usr/bin/kubectl exec zuultest -c sidecar -i /usr/bin/git-receive-pack /zuul/glance

Here is an example use of that script to push to a remote branch:

.. code-block:: console

   [root@kube-1 glance]# GIT_SSH="/root/gitssh.sh" git push kube HEAD:testbranch
   Counting objects: 3, done.
   Delta compression using up to 4 threads.
   Compressing objects: 100% (3/3), done.
   Writing objects: 100% (3/3), 281 bytes | 281.00 KiB/s, done.
   Total 3 (delta 2), reused 0 (delta 0)
   To git+ssh://kube/
    * [new branch]        HEAD -> testbranch

.. _sidecar pattern: https://docs.microsoft.com/en-us/azure/architecture/patterns/sidecar
.. _emptyDir volume: https://kubernetes.io/docs/concepts/storage/volumes/#emptydir

.. _buildset:

BuildSet Resources
------------------

It may be very desirable to construct a job graph which builds
container images once at the top, and then supports multiple jobs
which deploy and exercise those images.  The use of a private image
registry is particularly suited to this.

On the other hand, folks may want jobs in a buildset to be isolated
from each other, so we may not want to simply assume that all jobs in
a buildset are related.

An approach which is intuitive and doesn't preclude either approach is
to allow the user to tell Zuul that the resources used by a job (e.g.,
the Kubernetes namespace, and any containers or other nodes) should
continue running until the end of the buildset.  These resources would
then be placed in the inventory of child jobs for their use.  In this
way, the job we constructed earlier which built and image and uploaded
it into a registry that it hosted could then be the root of a tree of
child jobs which use that registry.  If the image-build-registry job
created a service token, that could be passed to the child jobs for
their use when they start their own containers or pods.

In order to support this, we may need to implement provider affinity
for builds in a buildset in Nodepool so that we don't have to deal
with ingress access to the registry (which may not be possible).
Otherwise if a Nodepool had access to two Kubernetes clusters, we
might assign a child job to a different cluster.
