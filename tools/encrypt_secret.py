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

import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import ssl

# we to import Request and urlopen differently for python 2 and 3
try:
    from urllib.request import Request
    from urllib.request import urlopen
    from urllib.parse import urlparse
except ImportError:
    from urllib2 import Request
    from urllib2 import urlopen
    from urlparse import urlparse

DESCRIPTION = """Encrypt a secret for Zuul.

This program fetches a project-specific public key from a Zuul server and
uses that to encrypt a secret.  The only pre-requisite is an installed
OpenSSL binary.
"""


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('url',
                        help="The base URL of the zuul server.  "
                        "E.g., https://zuul.example.com/ or path"
                        " to project public key file. E.g.,"
                        " file:///path/to/key.pub")
    parser.add_argument('project', default=None, nargs="?",
                        help="The name of the project. Required when using"
                        " the Zuul API to fetch the public key.")
    parser.add_argument('--tenant',
                        default=None,
                        help="The name of the Zuul tenant.  This may be "
                        "required in a multi-tenant environment.")
    parser.add_argument('--strip', action='store_true', default=False,
                        help="Strip whitespace from beginning/end of input.")
    parser.add_argument('--infile',
                        default=None,
                        help="A filename whose contents will be encrypted.  "
                        "If not supplied, the value will be read from "
                        "standard input.")
    parser.add_argument('--outfile',
                        default=None,
                        help="A filename to which the encrypted value will be "
                        "written.  If not supplied, the value will be written "
                        "to standard output.")
    parser.add_argument('--insecure', action='store_true', default=False,
                        help="Do not verify remote certificate")
    args = parser.parse_args()

    # We should not use unencrypted connections for retrieving the public key.
    # Otherwise our secret can be compromised. The schemes file and https are
    # considered safe.
    url = urlparse(args.url)
    if url.scheme not in ('file', 'https'):
        sys.stderr.write("WARNING: Retrieving encryption key via an "
                         "unencrypted connection. Your secret may get "
                         "compromised.\n")

    ssl_ctx = None
    if url.scheme == 'file':
        req = Request(args.url)
    else:
        if args.insecure:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        # Check if tenant is white label
        req = Request("%s/api/info" % (args.url.rstrip('/'),))
        info = json.loads(urlopen(req, context=ssl_ctx).read().decode('utf8'))

        api_tenant = info.get('info', {}).get('tenant')
        if not api_tenant and not args.tenant:
            print("Error: the --tenant argument is required")
            exit(1)

        if api_tenant:
            req = Request("%s/api/key/%s.pub" % (
                args.url.rstrip('/'), args.project))
        else:
            req = Request("%s/api/tenant/%s/key/%s.pub" % (
                args.url.rstrip('/'), args.tenant, args.project))
    pubkey = urlopen(req, context=ssl_ctx)

    if args.infile:
        with open(args.infile) as f:
            plaintext = f.read()
    else:
        plaintext = sys.stdin.read()

    plaintext = plaintext.encode("utf-8")
    if args.strip:
        plaintext = plaintext.strip()

    pubkey_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        pubkey_file.write(pubkey.read())
        pubkey_file.close()

        p = subprocess.Popen(['openssl', 'rsa', '-text',
                              '-pubin', '-in',
                              pubkey_file.name],
                             stdout=subprocess.PIPE)
        (stdout, stderr) = p.communicate()
        if p.returncode != 0:
            raise Exception("Return code %s from openssl" % p.returncode)
        output = stdout.decode('utf-8')
        openssl_version = subprocess.check_output(
            ['openssl', 'version']).split()[1]
        if openssl_version.startswith(b'0.'):
            key_length_re = r'^Modulus \((?P<key_length>\d+) bit\):$'
        else:
            key_length_re = r'^(|RSA )Public-Key: \((?P<key_length>\d+) bit\)$'
        m = re.match(key_length_re, output, re.MULTILINE)
        nbits = int(m.group('key_length'))
        nbytes = int(nbits / 8)
        max_bytes = nbytes - 42  # PKCS1-OAEP overhead
        chunks = int(math.ceil(float(len(plaintext)) / max_bytes))

        ciphertext_chunks = []

        print("Public key length: {} bits ({} bytes)".format(nbits, nbytes))
        print("Max plaintext length per chunk: {} bytes".format(max_bytes))
        print("Input plaintext length: {} bytes".format(len(plaintext)))
        print("Number of chunks: {}".format(chunks))

        for count in range(chunks):
            chunk = plaintext[int(count * max_bytes):
                              int((count + 1) * max_bytes)]
            p = subprocess.Popen(['openssl', 'rsautl', '-encrypt',
                                  '-oaep', '-pubin', '-inkey',
                                  pubkey_file.name],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE)
            (stdout, stderr) = p.communicate(chunk)
            if p.returncode != 0:
                raise Exception("Return code %s from openssl" % p.returncode)
            ciphertext_chunks.append(base64.b64encode(stdout).decode('utf-8'))

    finally:
        os.unlink(pubkey_file.name)

    output = textwrap.dedent(
        '''
        - secret:
            name: <name>
            data:
              <fieldname>: !encrypted/pkcs1-oaep
        ''')

    twrap = textwrap.TextWrapper(width=79,
                                 initial_indent=' ' * 8,
                                 subsequent_indent=' ' * 10)
    for chunk in ciphertext_chunks:
        chunk = twrap.fill('- ' + chunk)
        output += chunk + '\n'

    if args.outfile:
        with open(args.outfile, "w") as f:
            f.write(output)
    else:
        print(output)


if __name__ == '__main__':
    main()
