# Copyright 2018 Red Hat, Inc.
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

import tempfile
import logging
import os


class Migration(object):
    log = logging.getLogger("zuul.KeyStorage")
    version = 0
    parent = None

    def verify(self, root):
        fn = os.path.join(root, '.version')
        if not os.path.exists(fn):
            return False
        with open(fn) as f:
            data = int(f.read().strip())
            if data == self.version:
                return True
        return False

    def writeVersion(self, root):
        fn = os.path.join(root, '.version')
        with open(fn, 'w') as f:
            f.write(str(self.version))

    def upgrade(self, root):
        pass

    def verifyAndUpgrade(self, root):
        if self.verify(root):
            return
        if self.parent:
            self.parent.verifyAndUpgrade(root)
        self.log.info("Upgrading key storage to version %s" % self.version)
        self.upgrade(root)
        self.writeVersion(root)
        self.log.info("Finished upgrading key storage to version %s" %
                      self.version)
        if not self.verify(root):
            raise Exception("Inconsistent result after migration")


class MigrationV1(Migration):
    version = 1
    parent = None

    """Upgrade from the unversioned schema to version 1.

    The original schema had secret keys in key_dir/connection/project.pem

    This updates us to:
      key_dir/
        secrets/
          project/
            <connection>/
              <project>/
                <keyid>.pem
        ssh/
          project/
            <connection>/
              <project>/
                <keyid>.pem
          tenant/
            <tenant>/
              <keyid>.pem

    Where keyids are integers to support future key rollover.  In this
    case, they will all be 0.

    """

    def upgrade(self, root):
        tmpdir = tempfile.mkdtemp(dir=root)
        tmpdirname = os.path.basename(tmpdir)
        connection_names = []
        for connection_name in os.listdir(root):
            if connection_name == tmpdirname:
                continue
            # Move existing connections out of the way (in case one of
            # them was called 'secrets' or 'ssh'.
            os.rename(os.path.join(root, connection_name),
                      os.path.join(tmpdir, connection_name))
            connection_names.append(connection_name)
        os.makedirs(os.path.join(root, 'secrets', 'project'), 0o700)
        os.makedirs(os.path.join(root, 'ssh', 'project'), 0o700)
        os.makedirs(os.path.join(root, 'ssh', 'tenant'), 0o700)
        for connection_name in connection_names:
            connection_root = os.path.join(tmpdir, connection_name)
            for (dirpath, dirnames, filenames) in os.walk(connection_root):
                subdir = os.path.relpath(dirpath, connection_root)
                for fn in filenames:
                    key_name = os.path.join(subdir, fn)
                    project_name = key_name[:-len('.pem')]
                    key_dir = os.path.join(root, 'secrets', 'project',
                                           connection_name, project_name)
                    os.makedirs(key_dir, 0o700)
                    old = os.path.join(tmpdir, connection_name, key_name)
                    new = os.path.join(key_dir, '0.pem')
                    self.log.debug("Moving key from %s to %s", old, new)
                    os.rename(old, new)
            for (dirpath, dirnames, filenames) in os.walk(
                    connection_root, topdown=False):
                os.rmdir(dirpath)
        os.rmdir(tmpdir)


class KeyStorage(object):
    current_version = MigrationV1

    def __init__(self, root):
        self.root = root
        migration = self.current_version()
        migration.verifyAndUpgrade(root)

    def getProjectSecretsKeyFile(self, connection, project, version=None):
        """Return the path to the private key used for the project's secrets"""
        # We don't actually support multiple versions yet
        if version is None:
            version = '0'
        return os.path.join(self.root, 'secrets', 'project',
                            connection, project, version + '.pem')
