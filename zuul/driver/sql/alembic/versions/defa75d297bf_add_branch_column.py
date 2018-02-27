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

"""Add branch column

Revision ID: defa75d297bf
Revises: 19d3a3ebfe1d
Create Date: 2018-02-21 01:52:23.781875

"""

# revision identifiers, used by Alembic.
revision = 'defa75d297bf'
down_revision = '19d3a3ebfe1d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(table_prefix=''):
    op.add_column(
        table_prefix + 'zuul_buildset', sa.Column('branch', sa.String(255)))


def downgrade():
    raise Exception("Downgrades not supported")
