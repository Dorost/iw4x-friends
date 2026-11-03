"""initial tables

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("server", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_events_at"), ["at"], unique=False)

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("servers", sa.String(length=200), nullable=False),
        sa.Column("days", sa.String(length=20), nullable=False),
        sa.Column("start", sa.String(length=5), nullable=False),
        sa.Column("end", sa.String(length=5), nullable=False),
        sa.Column("tz", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "servers",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step", sa.String(length=200), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=True),
        sa.Column("volume_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("wg_public", sa.String(length=64), nullable=True),
        sa.Column("token", sa.String(length=64), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=True),
        sa.Column("boot_by", sa.String(length=64), nullable=False),
        sa.Column("booted_at", sa.Integer(), nullable=True),
        sa.Column("ready_at", sa.Integer(), nullable=True),
        sa.Column("last_human_at", sa.Integer(), nullable=True),
        sa.Column("hold_off_until", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("servers")
    op.drop_table("schedules")
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_at"))

    op.drop_table("events")
