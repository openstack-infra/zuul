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

"""add_artifact_table

Revision ID: ea2bae776723
Revises: f181b33958c6
Create Date: 2018-11-26 14:48:54.463512

"""

# revision identifiers, used by Alembic.
revision = 'ea2bae776723'
down_revision = 'f181b33958c6'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


ARTIFACT_TABLE = 'zuul_artifact'
BUILD_TABLE = 'zuul_build'


def upgrade(table_prefix=''):
    op.create_table(
        table_prefix + ARTIFACT_TABLE,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('build_id', sa.Integer,
                  sa.ForeignKey(table_prefix + BUILD_TABLE + ".id")),
        sa.Column('name', sa.String(255)),
        sa.Column('url', sa.TEXT()),
    )


def downgrade():
    raise Exception("Downgrades not supported")
