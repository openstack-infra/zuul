"""Allow score to be null

Revision ID: 1dd914d4a482
Revises: 4d3ebd7f06b9
Create Date: 2017-03-28 08:09:32.908643

"""

# revision identifiers, used by Alembic.
revision = '1dd914d4a482'
down_revision = '4d3ebd7f06b9'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(table_prefix=''):
    op.alter_column(table_prefix + 'zuul_buildset', 'score', nullable=True,
                    existing_type=sa.Integer)


def downgrade():
    raise Exception("Downgrades not supported")
