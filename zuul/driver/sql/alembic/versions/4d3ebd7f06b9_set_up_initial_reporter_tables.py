"""Set up initial reporter tables

Revision ID: 4d3ebd7f06b9
Revises:
Create Date: 2015-12-06 15:27:38.080020

"""

# revision identifiers, used by Alembic.
revision = '4d3ebd7f06b9'
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

BUILDSET_TABLE = 'zuul_buildset'
BUILD_TABLE = 'zuul_build'


def upgrade(table_prefix=''):
    op.create_table(
        table_prefix + BUILDSET_TABLE,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('zuul_ref', sa.String(255)),
        sa.Column('pipeline', sa.String(255)),
        sa.Column('project', sa.String(255)),
        sa.Column('change', sa.Integer, nullable=True),
        sa.Column('patchset', sa.Integer, nullable=True),
        sa.Column('ref', sa.String(255)),
        sa.Column('score', sa.Integer),
        sa.Column('message', sa.TEXT()),
    )

    op.create_table(
        table_prefix + BUILD_TABLE,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('buildset_id', sa.Integer,
                  sa.ForeignKey(table_prefix + BUILDSET_TABLE + ".id")),
        sa.Column('uuid', sa.String(36)),
        sa.Column('job_name', sa.String(255)),
        sa.Column('result', sa.String(255)),
        sa.Column('start_time', sa.DateTime()),
        sa.Column('end_time', sa.DateTime()),
        sa.Column('voting', sa.Boolean),
        sa.Column('log_url', sa.String(255)),
        sa.Column('node_name', sa.String(255)),
    )


def downgrade():
    raise Exception("Downgrades not supported")
