:title: Vulnerability Reporting

.. _vulnerability-reporting:

Vulnerability Reporting
=======================

Zuul strives to be as secure as possible, implementing a layered
defense-in-depth approach where any untrusted code is executed and
leveraging well-reviewed popular libraries for its cryptographic
needs. Still, bugs are inevitable and security bugs are no exception
to that rule.

If you've found a bug in Zuul and you suspect it may compromise the
security of some part of the system, we'd appreciate the opportunity
to privately discuss the details before any suspected vulnerability
is made public. There are a couple possible ways you can bring
security bugs to our attention:

Create a Private Story in StoryBoard
------------------------------------

You can create a private story at the following URL:

`<https://storyboard.openstack.org/#!/story/new?force_private=true>`_

Using this particular reporting URL helps prevent you from
forgetting to set the ``Private`` checkbox in the new story UI
before saving. If you're doing this from a normal story creation
workflow instead, please make sure to set this checkbox first.

Enter a short but memorable title for your vulnerability report and
provide risks, concerns or other relevant details in the description
field. Where it lists teams and users that can see this story, add
the ``zuul-security`` team so they'll be able to work on triaging
it. For the initial task, select the project to which this is
specific (e.g., ``openstack-infra/zuul`` or
``openstack-infra/nodepool``) and if it relates to additional
projects you can add another task for each of them making sure to
include a relevant title for each task. When you've included all the
detail and tasks you want, save the new story and then you can
continue commenting on it normally. Please don't remove the
``Private`` setting, and instead wait for one of the zuul-security
reviewers to do this once it's deemed safe.

Report via Encrypted E-mail
---------------------------

If the issue is extremely sensitive or you’re otherwise unable to
use the task tracker directly, please send an E-mail message to one
or more members of the Zuul security team. You’re encouraged to
encrypt messages to their OpenPGP keys, which can be found linked
below and also on the keyserver network with the following
fingerprints:

.. TODO: add some more contacts/keys here

* Jeremy Stanley <fungi@yuggoth.org>:
  `key 0x97ae496fc02dec9fc353b2e748f9961143495829`_ (details__)

* Tobias Henkel <tobias.henkel@bmw.de>:
  `key 0xfb2ee15b2f0f12662b68ed9603750dec158e5fa2`_ (details__)

.. _`key 0x97ae496fc02dec9fc353b2e748f9961143495829`: ../_static/0x97ae496fc02dec9fc353b2e748f9961143495829.txt
.. __: https://sks-keyservers.net/pks/lookup?op=vindex&search=0x97ae496fc02dec9fc353b2e748f9961143495829&fingerprint=on

.. _`key 0xfb2ee15b2f0f12662b68ed9603750dec158e5fa2`: ../_static/0xfb2ee15b2f0f12662b68ed9603750dec158e5fa2.txt
.. __: https://sks-keyservers.net/pks/lookup?op=vindex&search=0xfb2ee15b2f0f12662b68ed9603750dec158e5fa2&fingerprint=on
