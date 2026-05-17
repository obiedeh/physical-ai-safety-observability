"""initial sqlite schema

Revision ID: 0001_initial_sqlite_schema
Revises:
Create Date: 2026-05-16 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_sqlite_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("camera_id", sa.Text(), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("registered_at", sa.Text(), nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("incident_id", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        if_not_exists=True,
    )
    op.create_index("idx_events_timestamp", "events", ["timestamp"], if_not_exists=True)
    op.create_index("idx_events_incident", "events", ["incident_id"], if_not_exists=True)
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Text(), primary_key=True),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("grouping_severity", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "idx_incidents_grouping",
        "incidents",
        ["camera_id", "rule_id", "grouping_severity", "updated_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_incidents_grouping", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("idx_events_incident", table_name="events")
    op.drop_index("idx_events_timestamp", table_name="events")
    op.drop_table("events")
    op.drop_table("cameras")
