"""camera configs and runtime settings

Revision ID: 0003_camera_configs_and_settings
Revises: 0002_feedback_events
Create Date: 2026-10-02 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_camera_configs_and_settings"
down_revision: str | None = "0002_feedback_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "camera_configs",
        sa.Column("camera_id", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.Text(), nullable=False),  # JSON; password is Fernet-encrypted
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("camera_configs")
