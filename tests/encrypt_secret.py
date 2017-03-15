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

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes

FIXTURE_DIR = os.path.join(os.path.dirname(__file__),
                           'fixtures')


def main():
    private_key_file = os.path.join(FIXTURE_DIR, 'private.pem')
    with open(private_key_file, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend()
        )

    # Extract public key from private
    public_key = private_key.public_key()

    # https://cryptography.io/en/stable/hazmat/primitives/asymmetric/rsa/#encryption
    ciphertext = public_key.encrypt(
        sys.argv[1],
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None
        )
    )
    print(ciphertext.encode('base64'))

if __name__ == '__main__':
    main()
