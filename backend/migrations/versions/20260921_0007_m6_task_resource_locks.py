"""M6 persistent directory ownership.

Revision ID: 20260921_0007
Revises: 20260921_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0007"
down_revision = "20260921_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("task_resource_locks", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("resource_key", sa.String(80), nullable=False), sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.UniqueConstraint("resource_key", name="uq_task_resource_key"), mysql_charset="utf8mb4")
    op.create_index("ix_task_resource_locks_task_id", "task_resource_locks", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_resource_locks_task_id", table_name="task_resource_locks")
    op.drop_table("task_resource_locks")
