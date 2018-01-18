"""Change patchset to string

Revision ID: cfc0dc45f341
Revises: ba4cdce9b18c
Create Date: 2018-01-09 16:44:31.506958

"""

# revision identifiers, used by Alembic.
revision = 'cfc0dc45f341'
down_revision = 'ba4cdce9b18c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

BUILDSET_TABLE = 'zuul_buildset'


def upgrade(table_prefix=''):
    op.alter_column(table_prefix + BUILDSET_TABLE,
                    'patchset',
                    sa.String(255),
                    existing_nullable=True,
                    existing_type=sa.Integer)


def downgrade():
    raise Exception("Downgrades not supported")
