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
import yaml
from yaml import YAMLObject, YAMLError  # noqa: F401

try:
    # Explicit type ignore to deal with provisional import failure
    from yaml import cyaml  # type: ignore
    import _yaml
    SafeLoader = cyaml.CSafeLoader
    SafeDumper = cyaml.CSafeDumper
    Mark = _yaml.Mark
except ImportError:
    SafeLoader = yaml.SafeLoader
    SafeDumper = yaml.SafeDumper
    Mark = yaml.Mark


class UnsafeTag(yaml.YAMLObject):
    yaml_tag = u'!unsafe'

    def __init__(self, unsafe_var):
        self.unsafe_var = unsafe_var

    @classmethod
    def from_yaml(cls, loader, node):
        return UnsafeTag(node.value)

    @classmethod
    def to_yaml(cls, dumper, data):
        return dumper.represent_scalar(cls.yaml_tag, data.unsafe_var)

    def __str__(self):
        return self.unsafe_var


# Just calling SafeLoader and SafeDumper without yaml module prefix
# does not work and cyaml is using yaml.SafeConstructor yaml.SafeRepresenter
# underneath so this just fine for both
yaml.SafeLoader.add_constructor(UnsafeTag.yaml_tag, UnsafeTag.from_yaml)
yaml.SafeDumper.add_multi_representer(UnsafeTag, UnsafeTag.to_yaml)


def safe_load(stream, *args, **kwargs):
    return yaml.load(stream, *args, Loader=SafeLoader, **kwargs)


def safe_dump(stream, *args, **kwargs):
    return yaml.dump(stream, *args, Dumper=SafeDumper, **kwargs)
