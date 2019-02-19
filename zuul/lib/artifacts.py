# Copyright 2018-2019 Red Hat, Inc.
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

import voluptuous as v
import urllib.parse

artifact = {
    'name': v.Required(str),
    'url': v.Required(str),
    'metadata': dict,
}

zuul_data = {
    'zuul': {
        'log_url': str,
        'artifacts': [artifact],
        v.Extra: object,
    },
    v.Extra: object,
}

artifact_schema = v.Schema(zuul_data)


def validate_artifact_schema(data):
    try:
        artifact_schema(data)
    except Exception:
        return False
    return True


def get_artifacts_from_result_data(result_data, logger=None):
    ret = []
    if validate_artifact_schema(result_data):
        artifacts = result_data.get('zuul', {}).get(
            'artifacts', [])
        default_url = result_data.get('zuul', {}).get(
            'log_url')
        if default_url:
            if default_url[-1] != '/':
                default_url += '/'
        for artifact in artifacts:
            url = artifact['url']
            if default_url:
                # If the artifact url is relative, it will be combined
                # with the log_url; if it is absolute, it will replace
                # it.
                try:
                    url = urllib.parse.urljoin(default_url, url)
                except Exception:
                    if logger:
                        logger.debug("Error parsing URL:",
                                     exc_info=1)
            d = artifact.copy()
            d['url'] = url
            ret.append(d)
    else:
        logger.debug("Result data did not pass artifact schema "
                     "validation: %s", result_data)
    return ret
