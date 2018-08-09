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

import voluptuous as vs


FILE_COMMENT = {
    'line': int,
    'message': str,
    'range': {
        'start_line': int,
        'start_character': int,
        'end_line': int,
        'end_character': int,
    }
}

FILE_COMMENTS = {str: [FILE_COMMENT]}

FILE_COMMENTS_SCHEMA = vs.Schema(FILE_COMMENTS)


def validate(file_comments):
    FILE_COMMENTS_SCHEMA(file_comments)


def extractLines(file_comments):
    """Extract file/line tuples from file comments for mapping"""

    lines = set()
    for path, comments in file_comments.items():
        for comment in comments:
            if 'line' in comment:
                lines.add((path, int(comment['line'])))
            if 'range' in comment:
                rng = comment['rng']
                for key in ['start_line', 'end_line']:
                    if key in rng:
                        lines.add((path, int(rng[key])))
    return list(lines)


def updateLines(file_comments, lines):
    """Update the line numbers in file_comments with the supplied mapping"""

    for path, comments in file_comments.items():
        for comment in comments:
            if 'line' in comment:
                comment['line'] = lines.get((path, comment['line']),
                                            comment['line'])
            if 'range' in comment:
                rng = comment['rng']
                for key in ['start_line', 'end_line']:
                    if key in rng:
                        rng[key] = lines.get((path, rng[key]), rng[key])
