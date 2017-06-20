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
import os
import subprocess
import sys
import tempfile
import urllib

DESCRIPTION = """Encrypt a secret for Zuul.

This program fetches a project-specific public key from a Zuul server and
uses that to encrypt a secret.  The only pre-requisite is an installed
OpenSSL binary.
"""


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('url',
                        help="The base URL of the zuul server and tenant.  "
                        "E.g., https://zuul.example.com/tenant-name")
    # TODO(jeblair,mordred): When projects have canonical names, use that here.
    # TODO(jeblair): Throw a fit if SSL is not used.
    parser.add_argument('source',
                        help="The Zuul source of the project.")
    parser.add_argument('project',
                        help="The name of the project.")
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
    args = parser.parse_args()

    req = urllib.request.Request("%s/keys/%s/%s.pub" % (
        args.url, args.source, args.project))
    pubkey = urllib.request.urlopen(req)

    if args.infile:
        with open(args.infile) as f:
            plaintext = f.read()
    else:
        plaintext = sys.stdin.read()

    pubkey_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        pubkey_file.write(pubkey.read())
        pubkey_file.close()

        p = subprocess.Popen(['openssl', 'rsautl', '-encrypt',
                              '-oaep', '-pubin', '-inkey',
                              pubkey_file.name],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE)
        (stdout, stderr) = p.communicate(plaintext)
        if p.returncode != 0:
            raise Exception("Return code %s from openssl" % p.returncode)
        ciphertext = stdout.encode('base64')
    finally:
        os.unlink(pubkey_file.name)

    if args.outfile:
        with open(args.outfile, "w") as f:
            f.write(ciphertext)
    else:
        print(ciphertext)


if __name__ == '__main__':
    main()
