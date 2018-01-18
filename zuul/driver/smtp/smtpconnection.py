# Copyright 2014 Rackspace Australia
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
import voluptuous as v
import smtplib

from email.mime.text import MIMEText

from zuul.connection import BaseConnection


class SMTPConnection(BaseConnection):
    driver_name = 'smtp'
    log = logging.getLogger("zuul.SMTPConnection")

    def __init__(self, driver, connection_name, connection_config):
        super(SMTPConnection, self).__init__(driver, connection_name,
                                             connection_config)

        self.smtp_server = self.connection_config.get(
            'server', 'localhost')
        self.smtp_port = self.connection_config.get('port', 25)
        self.smtp_default_from = self.connection_config.get(
            'default_from', 'zuul')
        self.smtp_default_to = self.connection_config.get(
            'default_to', 'zuul')

    def sendMail(self, subject, message, from_email=None, to_email=None):
        # Create a text/plain email message
        from_email = from_email \
            if from_email is not None else self.smtp_default_from
        to_email = to_email if to_email is not None else self.smtp_default_to

        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email

        try:
            s = smtplib.SMTP(self.smtp_server, self.smtp_port)
            s.sendmail(from_email, to_email.split(','), msg.as_string())
            s.quit()
        except Exception:
            return "Could not send email via SMTP"
        return


def getSchema():
    smtp_connection = v.Any(str, v.Schema(dict))
    return smtp_connection
