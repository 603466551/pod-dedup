"""Allow the longest hashed resource key prefix.

Revision ID: 20260921_0008
Revises: 20260921_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0008"
down_revision = "20260921_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("task_resource_locks", "resource_key", existing_type=sa.String(80), type_=sa.String(96), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("task_resource_locks", "resource_key", existing_type=sa.String(96), type_=sa.String(80), existing_nullable=False)
