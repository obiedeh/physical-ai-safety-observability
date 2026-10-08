"""uploaded video files

Revision ID: 0004_uploads
Revises: 0003_camera_configs_and_settings
Create Date: 2026-10-08 00:00:00

Adds the ``uploads`` table behind the "Uploaded video" camera profile. The
file bytes live next to the database (``<db dir>/uploads``); the row keeps
the name, size, hash, declared source kind (recorded or generated) and the
stream properties read at upload time. Camera rows are JSON payloads, so the
new camera fields need no column change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_uploads"
down_revision: str | None = "0003_camera_configs_and_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("stored_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False, server_default="recorded"),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("codec", sa.Text(), nullable=True),
        sa.Column("frames", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("uploads")
