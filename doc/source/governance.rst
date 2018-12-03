Zuul Project Governance
=======================

The governance of the Zuul project is described below.  Changes to
this page should remain open for a week and require more positive than
negative Code-Review votes from the Maintainers before merging.  They
should only be approved by the Project Lead.

Zuul Maintainers
----------------

The Zuul project is self-governed.

Decisions regarding the project are made by the Zuul Maintainers.
They are a team of people who are familiar with the project as a whole
and act as stewards of the project.  They have the right to approve or
reject proposed changes to the codebase, as well as make other
decisions regarding the project.

The Maintainers are expected to be familiar with the source code,
design, operation, and usage of all parts of the Zuul project.  When
acting in their capacity as Maintainers, they are expected to consider
not only their own needs, but those of the entire community.

Changes to the code, documentation, website, and other project
resources held in version control repositories are reviewed and
approved by the Maintainers.  In general, approval is sought from at
least two maintainers before merging a change, but fewer or more
reviews may be warranted depending on the change.  Factors to consider
when reviewing are the complexity of the change, whether it is in
accordance with the project design, and whether additional project
participants with subject matter expertise should review the change.
Maintainers may also reject changes outright, but this is expected to
be used sparingly in favor of (or in the process of) redirecting
effort toward efforts which can achieve consensus.

The purpose of this review process is two-fold: first, to ensure that
changes to the project meet sufficiently high standards so that they
improve the project, contribute to furthering its goals, and do not
introduce regressive behavior or make the project more difficult to
support in the future.  Secondly, and just as important, the process
also ensures that contributors are aware of the changes to the
project.  In a distributed environment, reviews are an important part
of our collaborative process.

Project decisions other than those involving on-line review are
discussed on the project mailing list.  Anyone is welcome and
encouraged to participate in these discussions so that input from the
broader community is received.  As the authority, Maintainers should
strive to achieve consensus on any such decisions.

Changes to the membership of the Maintainers are decided by consensus
of the existing maintainers, however, due to their sensitivity, these
discussions should occur via private communication among the
maintainers under the direction of the Project Lead.

A large group of Maintainers is important for the health of the
project, therefore contributors are encouraged to become involved in
all facets of maintenance of the project as part of the process of
becoming a Maintainer.  Existing Maintainers are expected to encourage
new members.  There are no artificial limits of the number of
Maintainers.  The Project Lead will assist any contributor who wishes
for guidance in becoming a Maintainer.

Current Zuul Maintainers:

======================  =============
Name                    Freenode Nick
======================  =============
Clark Boylan            clarkb
Clint Byrum             SpamapS
David Shrewsbury        Shrews
Ian Wienand             ianw
James E. Blair          corvus
Jens Harbott            frickler
Jeremy Stanley          fungi
Jesse Keating           jlk
Joshua Hesketh          jhesketh
Monty Taylor            mordred
Paul Belanger           pabelanger
Ricardo Carrillo Cruz   rcarrillocruz
Tobias Henkel           tobiash
======================  =============

Zuul Project Lead
-----------------

The Maintainers elect a Project Lead to articulate the overall
direction of the project and promote consistency among the different
areas and aspects of the project.  The Project Lead does not have
extra rights beyond those of the Maintainers, but does have extra
responsibilities.  The Project Lead must pay particular attention to
the overall design and direction of the project, ensure that
Maintainers and other contributors are familiar with that design, and
facilitate achieving consensus on difficult issues.

If the project is unable to achieve consensus on an issue, the Project
Lead may poll the Maintainers on the issue, and in the case of a tie,
the vote of the Project Lead will be the tie-breaker.

The Project Lead is elected to a term of one year.  The election
process shall be a Condorcet election and the candidates shall be
self-nominated from among the existing Maintainers.

The Project Lead is James E. Blair (term expires 2020-01-14).

Zuul-Jobs Maintainers
---------------------

The zuul-jobs and zuul-base-jobs repositories contain a standard
library of reusable job components which are designed to be used in a
wide variety of situations.

Changes to these repositories require consideriation of the various
environments in which the jobs may be used as well as policies which
promote the consistency and stability of the components therein, but
not necessarily the full scope of Zuul development.  To that end,
approval rights for changes to these repositories are granted to both
the Zuul Maintainers and an additional group known as the Zuul-Jobs
Maintainers.  The reviewing processes are identical to the rest of the
project; membership changes to the Zuul-Jobs Maintainers group are
undertaken with consensus of the wider Zuul-Jobs group (not merely the
Zuul Maintainers).

Current Zuul-Jobs Maintainers (in addition to Zuul Maintainers):

======================  =============
Name                    Freenode Nick
======================  =============
Andreas Jaeger          AJaeger
David Moreau Simard     dmsimard
Mohammed Naser          mnaser
======================  =============
