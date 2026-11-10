"""time played: sessions

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("log", sa.String(length=32), nullable=False),
        sa.Column("node_session", sa.Integer(), nullable=False),
        sa.Column("guid", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("since", sa.Integer(), nullable=False),
        sa.Column("until", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server", "log", "node_session"),
    )
    for col in ("server", "run_id", "guid", "until"):
        op.create_index(f"ix_sessions_{col}", "sessions", [col])


def downgrade() -> None:
    op.drop_table("sessions")
