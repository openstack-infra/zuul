"""Change patchset to string

Revision ID: 19d3a3ebfe1d
Revises: cfc0dc45f341
Create Date: 2018-01-10 07:42:16.546751

"""

# revision identifiers, used by Alembic.
revision = '19d3a3ebfe1d'
down_revision = 'cfc0dc45f341'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

BUILDSET_TABLE = 'zuul_buildset'


def upgrade(table_prefix=''):
    op.alter_column(table_prefix + BUILDSET_TABLE,
                    'patchset',
                    type_=sa.String(255),
                    existing_nullable=True)


def downgrade():
    raise Exception("Downgrades not supported")
