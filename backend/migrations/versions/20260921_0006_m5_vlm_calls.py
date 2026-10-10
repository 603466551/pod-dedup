"""M5 auditable VLM calls.

Revision ID: 20260921_0006
Revises: 20260921_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0006"
down_revision = "20260921_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("vlm_calls", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("pair_id", sa.BigInteger(), sa.ForeignKey("duplicate_pairs.id"), nullable=True), sa.Column("provider", sa.String(64), nullable=False), sa.Column("model", sa.String(128), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("request_metadata", sa.JSON(), nullable=False), sa.Column("response_json", sa.JSON(), nullable=True), sa.Column("error_code", sa.String(64), nullable=True), sa.Column("error_message", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), mysql_charset="utf8mb4")
    op.create_index("ix_vlm_calls_task_id", "vlm_calls", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_vlm_calls_task_id", table_name="vlm_calls")
    op.drop_table("vlm_calls")
