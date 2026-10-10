"""Persisted operator settings for new tasks.

Revision ID: 20260921_0009
Revises: 20260921_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0009"
down_revision = "20260921_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("app_settings")
