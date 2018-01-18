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

"""Add tenant column

Revision ID: f86c9871ee67
Revises: 20126015a87d
Create Date: 2017-07-17 05:47:48.189767

"""

# revision identifiers, used by Alembic.
revision = 'f86c9871ee67'
down_revision = '20126015a87d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(table_prefix=''):
    op.add_column(
        table_prefix + 'zuul_buildset', sa.Column('tenant', sa.String(255)))


def downgrade():
    raise Exception("Downgrades not supported")
