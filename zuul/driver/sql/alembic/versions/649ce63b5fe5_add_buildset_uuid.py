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

"""Add uuid to buldset

Revision ID: 649ce63b5fe5
Revises: ea2bae776723
Create Date: 2019-01-11 06:17:40.042738

"""

# revision identifiers, used by Alembic.
revision = '649ce63b5fe5'
down_revision = 'ea2bae776723'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(table_prefix=''):
    op.add_column(
        table_prefix + 'zuul_buildset', sa.Column('uuid', sa.String(36)))


def downgrade():
    raise Exception("Downgrades not supported")
