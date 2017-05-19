# Copyright 2017 Red Hat, Inc.
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

import os
import subprocess
import tempfile

from zuul.lib import encryption

from tests.base import BaseTestCase


class TestEncryption(BaseTestCase):

    def setUp(self):
        super(TestEncryption, self).setUp()
        self.private, self.public = encryption.generate_rsa_keypair()

    def test_serialization(self):
        "Verify key serialization"
        pem_private = encryption.serialize_rsa_private_key(self.private)
        private2, public2 = encryption.deserialize_rsa_keypair(pem_private)

        # cryptography public / private key objects don't implement
        # equality testing, so we make sure they have the same numbers.
        self.assertEqual(self.private.private_numbers(),
                         private2.private_numbers())
        self.assertEqual(self.public.public_numbers(),
                         public2.public_numbers())

    def test_pkcs1_oaep(self):
        "Verify encryption and decryption"
        orig_plaintext = b"some text to encrypt"
        ciphertext = encryption.encrypt_pkcs1_oaep(orig_plaintext, self.public)
        plaintext = encryption.decrypt_pkcs1_oaep(ciphertext, self.private)
        self.assertEqual(orig_plaintext, plaintext)

    def test_openssl_pkcs1_oaep(self):
        "Verify that we can decrypt something encrypted with OpenSSL"
        orig_plaintext = b"some text to encrypt"
        pem_public = encryption.serialize_rsa_public_key(self.public)
        public_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            public_file.write(pem_public)
            public_file.close()

            p = subprocess.Popen(['openssl', 'rsautl', '-encrypt',
                                  '-oaep', '-pubin', '-inkey',
                                  public_file.name],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE)
            (stdout, stderr) = p.communicate(orig_plaintext)
            ciphertext = stdout
        finally:
            os.unlink(public_file.name)

        plaintext = encryption.decrypt_pkcs1_oaep(ciphertext, self.private)
        self.assertEqual(orig_plaintext, plaintext)
