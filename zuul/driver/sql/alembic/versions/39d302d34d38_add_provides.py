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

"""add_provides

Revision ID: 39d302d34d38
Revises: 649ce63b5fe5
Create Date: 2019-01-28 15:01:07.408072

"""

# revision identifiers, used by Alembic.
revision = '39d302d34d38'
down_revision = '649ce63b5fe5'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


PROVIDES_TABLE = 'zuul_provides'
BUILD_TABLE = 'zuul_build'


def upgrade(table_prefix=''):
    op.create_table(
        table_prefix + PROVIDES_TABLE,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('build_id', sa.Integer,
                  sa.ForeignKey(table_prefix + BUILD_TABLE + ".id")),
        sa.Column('name', sa.String(255)),
    )


def downgrade():
    raise Exception("Downgrades not supported")
