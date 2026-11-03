"""a server can be open to everyone instead of the join password

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("join_public", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.drop_column("join_public")
