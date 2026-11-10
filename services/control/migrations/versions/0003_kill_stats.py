"""kill stats: runs, people and their game identities, matches, kills

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stats_log", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("stats_seq", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server", sa.String(length=32), nullable=False),
        sa.Column("booted_at", sa.Integer(), nullable=False),
        sa.Column("ready_at", sa.Integer(), nullable=True),
        sa.Column("stopped_at", sa.Integer(), nullable=True),
        sa.Column("boot_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_server", "runs", ["server"])

    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "players",
        sa.Column("guid", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("first_seen", sa.Integer(), nullable=False),
        sa.Column("last_seen", sa.Integer(), nullable=False),
        sa.Column("dismissed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index("ix_players_person_id", "players", ["person_id"])

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("log", sa.String(length=32), nullable=False),
        sa.Column("node_match", sa.Integer(), nullable=False),
        sa.Column("map", sa.String(length=64), nullable=False),
        sa.Column("map_name", sa.String(length=64), nullable=False),
        sa.Column("gametype", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("mode_name", sa.String(length=64), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server", "log", "node_match"),
    )
    op.create_index("ix_matches_run_id", "matches", ["run_id"])

    op.create_table(
        "kills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("log", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("killer_guid", sa.String(length=64), nullable=True),
        sa.Column("killer_name", sa.String(length=64), nullable=False),
        sa.Column("killer_bot", sa.Boolean(), nullable=False),
        sa.Column("killer_team", sa.String(length=16), nullable=False),
        sa.Column("killer_ping", sa.Integer(), nullable=True),
        sa.Column("victim_guid", sa.String(length=64), nullable=False),
        sa.Column("victim_name", sa.String(length=64), nullable=False),
        sa.Column("victim_bot", sa.Boolean(), nullable=False),
        sa.Column("victim_team", sa.String(length=16), nullable=False),
        sa.Column("victim_ping", sa.Integer(), nullable=True),
        sa.Column("weapon", sa.String(length=64), nullable=False),
        sa.Column("means", sa.String(length=32), nullable=False),
        sa.Column("hit", sa.String(length=32), nullable=False),
        sa.Column("damage", sa.Integer(), nullable=False),
        sa.Column("headshot", sa.Boolean(), nullable=False),
        sa.Column("suicide", sa.Boolean(), nullable=False),
        sa.Column("team_kill", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server", "log", "seq"),
    )
    for col in ("server", "run_id", "match_id", "at", "killer_guid", "victim_guid"):
        op.create_index(f"ix_kills_{col}", "kills", [col])


def downgrade() -> None:
    op.drop_table("kills")
    op.drop_table("matches")
    op.drop_table("players")
    op.drop_table("people")
    op.drop_table("runs")
    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.drop_column("stats_seq")
        batch_op.drop_column("stats_log")
        batch_op.drop_column("run_id")
