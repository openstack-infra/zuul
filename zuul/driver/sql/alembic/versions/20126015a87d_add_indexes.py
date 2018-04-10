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

"""add indexes

Revision ID: 20126015a87d
Revises: 1dd914d4a482
Create Date: 2017-07-07 07:17:27.992040

"""

# revision identifiers, used by Alembic.
revision = '20126015a87d'
down_revision = '1dd914d4a482'
branch_labels = None
depends_on = None

from alembic import op

BUILDSET_TABLE = 'zuul_buildset'
BUILD_TABLE = 'zuul_build'


def upgrade(table_prefix=''):
    prefixed_buildset = table_prefix + BUILDSET_TABLE
    prefixed_build = table_prefix + BUILD_TABLE

    # To allow a dashboard to show a per-project view, optionally filtered
    # by pipeline.
    op.create_index(
        table_prefix + 'project_pipeline_idx',
        prefixed_buildset, ['project', 'pipeline'])

    # To allow a dashboard to show a per-project-change view
    op.create_index(
        table_prefix + 'project_change_idx',
        prefixed_buildset, ['project', 'change'])

    # To allow a dashboard to show a per-change view
    op.create_index(table_prefix + 'change_idx', prefixed_buildset, ['change'])

    # To allow a dashboard to show a job lib view. buildset_id is included
    # so that it's a covering index and can satisfy the join back to buildset
    # without an additional lookup.
    op.create_index(
        table_prefix + 'job_name_buildset_id_idx', prefixed_build,
        ['job_name', 'buildset_id'])


def downgrade():
    raise Exception("Downgrades not supported")
