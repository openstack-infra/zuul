# Copyright 2013 Rackspace Australia
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging
import smtplib

from email.mime.text import MIMEText


class Reporter(object):
    """Sends off reports to emails via SMTP."""

    name = 'smtp'
    log = logging.getLogger("zuul.reporter.smtp.Reporter")

    def __init__(self, smtp_default_from, smtp_default_to,
                 smtp_server='localhost', smtp_port=25):
        """Set up the reporter.

        Takes parameters for the smtp server.
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_default_from = smtp_default_from
        self.smtp_default_to = smtp_default_to

    def report(self, source, change, message, params):
        """Send the compiled report message via smtp."""
        self.log.debug("Report change %s, params %s, message: %s" %
                       (change, params, message))

        # Create a text/plain email message
        from_email = params['from']\
            if 'from' in params else self.smtp_default_from
        to_email = params['to']\
            if 'to' in params else self.smtp_default_to
        msg = MIMEText(message)
        if 'subject' in params:
            subject = params['subject'].format(change=change)
        else:
            subject = "Report for change %s" % change
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email

        try:
            s = smtplib.SMTP(self.smtp_server, self.smtp_port)
            s.sendmail(from_email, to_email.split(','), msg.as_string())
            s.quit()
        except:
            return "Could not send email via SMTP"
        return

    def getSubmitAllowNeeds(self, params):
        """Get a list of code review labels that are allowed to be
        "needed" in the submit records for a change, with respect
        to this queue.  In other words, the list of review labels
        this reporter itself is likely to set before submitting.
        """
        return []
