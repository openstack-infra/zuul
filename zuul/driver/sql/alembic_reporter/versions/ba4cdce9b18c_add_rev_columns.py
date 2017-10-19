"""Add oldrev/newrev columns

Revision ID: ba4cdce9b18c
Revises: 5efb477fa963
Create Date: 2017-09-27 19:33:21.800198

"""

# revision identifiers, used by Alembic.
revision = 'ba4cdce9b18c'
down_revision = '5efb477fa963'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('zuul_buildset', sa.Column('oldrev', sa.String(255)))
    op.add_column('zuul_buildset', sa.Column('newrev', sa.String(255)))


def downgrade():
    op.drop_column('zuul_buildset', 'newrev')
    op.drop_column('zuul_buildset', 'oldrev')
