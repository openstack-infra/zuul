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

import hmac
from hashlib import sha1
import logging
from time import time
import os
import random
import six
import string
import urlparse


class Swift(object):
    log = logging.getLogger("zuul.lib.swift")

    def __init__(self, config):
        self.config = config
        self.connection = False
        if self.config.has_option('swift', 'X-Account-Meta-Temp-Url-Key'):
            self.secure_key = self.config.get('swift',
                                              'X-Account-Meta-Temp-Url-Key')
        else:
            self.secure_key = ''.join(
                random.choice(string.ascii_uppercase + string.digits)
                for x in range(20)
            )

        self.storage_url = ''
        if self.config.has_option('swift', 'X-Storage-Url'):
            self.storage_url = self.config.get('swift', 'X-Storage-Url')

        try:
            if self.config.has_section('swift'):
                if (not self.config.has_option('swift', 'Send-Temp-Url-Key')
                    or self.config.getboolean('swift',
                                              'Send-Temp-Url-Key')):
                    self.connect()

                    # Tell swift of our key
                    headers = {}
                    headers['X-Account-Meta-Temp-Url-Key'] = self.secure_key
                    self.connection.post_account(headers)

                if not self.config.has_option('swift', 'X-Storage-Url'):
                    self.connect()
                    self.storage_url = self.connection.get_auth()[0]
        except Exception as e:
            self.log.warning("Unable to set up swift. Signed storage URL is "
                             "likely to be wrong. %s" % e)

    def connect(self):
        if not self.connection:
            authurl = self.config.get('swift', 'authurl')

            user = (self.config.get('swift', 'user')
                    if self.config.has_option('swift', 'user') else None)
            key = (self.config.get('swift', 'key')
                   if self.config.has_option('swift', 'key') else None)
            retries = (self.config.get('swift', 'retries')
                       if self.config.has_option('swift', 'retries') else 5)
            preauthurl = (self.config.get('swift', 'preauthurl')
                          if self.config.has_option('swift', 'preauthurl')
                          else None)
            preauthtoken = (self.config.get('swift', 'preauthtoken')
                            if self.config.has_option('swift', 'preauthtoken')
                            else None)
            snet = (self.config.get('swift', 'snet')
                    if self.config.has_option('swift', 'snet') else False)
            starting_backoff = (self.config.get('swift', 'starting_backoff')
                                if self.config.has_option('swift',
                                                          'starting_backoff')
                                else 1)
            max_backoff = (self.config.get('swift', 'max_backoff')
                           if self.config.has_option('swift', 'max_backoff')
                           else 64)
            tenant_name = (self.config.get('swift', 'tenant_name')
                           if self.config.has_option('swift', 'tenant_name')
                           else None)
            auth_version = (self.config.get('swift', 'auth_version')
                            if self.config.has_option('swift', 'auth_version')
                            else 2.0)
            cacert = (self.config.get('swift', 'cacert')
                      if self.config.has_option('swift', 'cacert') else None)
            insecure = (self.config.get('swift', 'insecure')
                        if self.config.has_option('swift', 'insecure')
                        else False)
            ssl_compression = (self.config.get('swift', 'ssl_compression')
                               if self.config.has_option('swift',
                                                         'ssl_compression')
                               else True)

            available_os_options = ['tenant_id', 'auth_token', 'service_type',
                                    'endpoint_type', 'tenant_name',
                                    'object_storage_url', 'region_name']

            os_options = {}
            for os_option in available_os_options:
                if self.config.has_option('swift', os_option):
                    os_options[os_option] = self.config.get('swift', os_option)

            import swiftclient
            self.connection = swiftclient.client.Connection(
                authurl=authurl, user=user, key=key, retries=retries,
                preauthurl=preauthurl, preauthtoken=preauthtoken, snet=snet,
                starting_backoff=starting_backoff, max_backoff=max_backoff,
                tenant_name=tenant_name, os_options=os_options,
                auth_version=auth_version, cacert=cacert, insecure=insecure,
                ssl_compression=ssl_compression)

    def generate_form_post_middleware_params(self, destination_prefix='',
                                             **kwargs):
        """Generate the FormPost middleware params for the given settings"""

        # Define the available settings and their defaults
        settings = {
            'container': '',
            'expiry': 7200,
            'max_file_size': 104857600,
            'max_file_count': 10,
            'file_path_prefix': ''
        }

        for key, default in six.iteritems(settings):
            # TODO(jeblair): Remove the following two lines after a
            # deprecation period for the underscore variants of the
            # settings in YAML.
            if key in kwargs:
                settings[key] = kwargs[key]
            # Since we prefer '-' rather than '_' in YAML, look up
            # keys there using hyphens.  Continue to use underscores
            # everywhere else.
            altkey = key.replace('_', '-')
            if altkey in kwargs:
                settings[key] = kwargs[altkey]
            elif self.config.has_option('swift', 'default_' + key):
                settings[key] = self.config.get('swift', 'default_' + key)

        expires = int(time() + settings['expiry'])
        redirect = ''

        url = os.path.join(self.storage_url, settings['container'],
                           settings['file_path_prefix'],
                           destination_prefix)
        u = urlparse.urlparse(url)

        hmac_body = '%s\n%s\n%s\n%s\n%s' % (u.path, redirect,
                                            settings['max_file_size'],
                                            settings['max_file_count'],
                                            expires)

        signature = hmac.new(self.secure_key, hmac_body, sha1).hexdigest()

        return url, hmac_body, signature
