"""Use build_set results

Revision ID: 60c119eb1e3f
Revises: f86c9871ee67
Create Date: 2017-07-27 17:09:20.374782

"""

# revision identifiers, used by Alembic.
revision = '60c119eb1e3f'
down_revision = 'f86c9871ee67'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

BUILDSET_TABLE = 'zuul_buildset'


def upgrade(table_prefix=''):
    op.add_column(
        table_prefix + BUILDSET_TABLE, sa.Column('result', sa.String(255)))

    connection = op.get_bind()
    connection.execute(
        """
        UPDATE {buildset_table}
         SET result=(
             SELECT CASE score
                WHEN 1 THEN 'SUCCESS'
                ELSE 'FAILURE' END)
        """.format(buildset_table=table_prefix + BUILDSET_TABLE))

    op.drop_column(table_prefix + BUILDSET_TABLE, 'score')


def downgrade():
    raise Exception("Downgrades not supported")
