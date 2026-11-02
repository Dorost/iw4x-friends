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
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("starts_at", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("match_on", sa.Boolean(), nullable=False),
        sa.Column("reminded_30", sa.Boolean(), nullable=False),
        sa.Column("reminded_5", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plans_starts_at"), ["starts_at"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("tz", sa.String(length=64), nullable=True),
        sa.Column("ingame", sa.String(length=64), nullable=True),
        sa.Column("dm", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rsvps",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("plan_id", "user_id"),
    )
    op.create_table(
        "slots",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "weekday", "hour"),
    )
    op.create_table(
        "watches",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("watches")
    op.drop_table("slots")
    op.drop_table("rsvps")
    op.drop_table("users")
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plans_starts_at"))

    op.drop_table("plans")
