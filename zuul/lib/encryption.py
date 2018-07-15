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

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from functools import lru_cache


# https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#generation
def generate_rsa_keypair():
    """Generate an RSA keypair.

    :returns: A tuple (private_key, public_key)

    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
        backend=default_backend()
    )
    public_key = private_key.public_key()
    return (private_key, public_key)


# https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#key-serialization
def serialize_rsa_private_key(private_key):
    """Serialize an RSA private key

    This returns a PEM-encoded serialized form of an RSA private key
    suitable for storing on disk.  It is not password-protected.

    :arg private_key: A private key object as returned by
        :func:generate_rsa_keypair()

    :returns: A PEM-encoded string representation of the private key.

    """
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )


def serialize_rsa_public_key(public_key):
    """Serialize an RSA public key

    This returns a PEM-encoded serialized form of an RSA public key
    suitable for distribution.

    :arg public_key: A pubilc key object as returned by
        :func:generate_rsa_keypair()

    :returns: A PEM-encoded string representation of the public key.

    """
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )


# https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#key-loading
def deserialize_rsa_keypair(data):
    """Deserialize an RSA private key

    This deserializes an RSA private key and returns the keypair
    (private and public) for use in decryption.

    :arg data: A PEM-encoded serialized private key

    :returns: A tuple (private_key, public_key)

    """
    private_key = serialization.load_pem_private_key(
        data,
        password=None,
        backend=default_backend()
    )
    public_key = private_key.public_key()
    return (private_key, public_key)


# https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#decryption
# lru_cache performs best if maxsize is a power of two
@lru_cache(maxsize=1024)
def decrypt_pkcs1_oaep(ciphertext, private_key):
    """Decrypt PKCS#1 (RSAES-OAEP) encoded ciphertext

    :arg ciphertext: A string previously encrypted with PKCS#1
        (RSAES-OAEP).
    :arg private_key: A private key object as returned by
        :func:generate_rsa_keypair()

    :returns: The decrypted form of the ciphertext as a string.

    """
    return private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None
        )
    )


# https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#encryption
def encrypt_pkcs1_oaep(plaintext, public_key):
    """Encrypt data with PKCS#1 (RSAES-OAEP)

    :arg plaintext: A string to encrypt with PKCS#1 (RSAES-OAEP).

    :arg public_key: A public key object as returned by
        :func:generate_rsa_keypair()

    :returns: The encrypted form of the plaintext.

    """
    return public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None
        )
    )
