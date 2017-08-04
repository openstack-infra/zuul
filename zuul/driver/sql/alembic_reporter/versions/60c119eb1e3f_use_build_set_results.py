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


def upgrade():
    op.add_column(BUILDSET_TABLE, sa.Column('result', sa.String(255)))

    connection = op.get_bind()
    connection.execute(
        """
        UPDATE {buildset_table}
         SET result=(
             SELECT CASE score
                WHEN 1 THEN 'SUCCESS'
                ELSE 'FAILURE' END)
        """.format(buildset_table=BUILDSET_TABLE))

    op.drop_column(BUILDSET_TABLE, 'score')


def downgrade():
    op.add_column(BUILDSET_TABLE, sa.Column('score', sa.Integer))

    connection = op.get_bind()
    connection.execute(
        """
        UPDATE {buildset_table}
         SET score=(
             SELECT CASE result
                WHEN 'SUCCESS' THEN 1
                ELSE -1 END)
        """.format(buildset_table=BUILDSET_TABLE))
    op.drop_column(BUILDSET_TABLE, 'result')
