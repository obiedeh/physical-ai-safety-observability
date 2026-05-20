"""add person ppe feedback table

Revision ID: 0002_feedback_events
Revises: 0001_initial_sqlite_schema
Create Date: 2026-05-20 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_feedback_events"
down_revision: str | None = "0001_initial_sqlite_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("feedback_id", sa.Text(), primary_key=True),
        sa.Column("camera_id", sa.Text(), nullable=False),
        sa.Column("frame_id", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        if_not_exists=True,
    )
    op.create_index("idx_feedback_timestamp", "feedback", ["timestamp"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_feedback_timestamp", table_name="feedback")
    op.drop_table("feedback")
