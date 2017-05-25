#!/usr/bin/env python

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

import sys
import os

from zuul.lib import encryption

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')


def main():
    private_key_file = os.path.join(FIXTURE_DIR, 'private.pem')
    with open(private_key_file, "rb") as f:
        private_key, public_key = \
            encryption.deserialize_rsa_keypair(f.read())

    ciphertext = encryption.encrypt_pkcs1_oaep(sys.argv[1], public_key)
    print(ciphertext.encode('base64'))


if __name__ == '__main__':
    main()
