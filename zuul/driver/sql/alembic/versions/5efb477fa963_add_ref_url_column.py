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

"""Add ref_url column

Revision ID: 5efb477fa963
Revises: 60c119eb1e3f
Create Date: 2017-09-12 22:50:29.307695

"""

# revision identifiers, used by Alembic.
revision = '5efb477fa963'
down_revision = '60c119eb1e3f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(table_prefix=''):
    op.add_column(
        table_prefix + 'zuul_buildset', sa.Column('ref_url', sa.String(255)))


def downgrade():
    raise Exception("Downgrades not supported")
