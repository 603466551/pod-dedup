"""M1 task persistence.

Revision ID: 20260920_0001
Revises:
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260920_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_batch_dir", sa.Text()),
        sa.Column("source_library_dir", sa.Text()),
        sa.Column("pod_pending_dir", sa.Text()),
        sa.Column("pod_library_dir", sa.Text()),
        sa.Column("ratio_code", sa.String(length=8)),
        sa.Column("archive_date", sa.Date()),
        sa.Column("settings_snapshot", sa.JSON(), nullable=False),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("lease_owner", sa.String(length=80)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tasks_type", "tasks", ["type"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_type", table_name="tasks")
    op.drop_table("tasks")

