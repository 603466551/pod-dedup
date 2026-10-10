"""M2 image identity and file operation audit.

Revision ID: 20260920_0002
Revises: 20260920_0001
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260920_0002"
down_revision = "20260920_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("sha256", sa.BINARY(32)), sa.Column("pixel_digest", sa.BINARY(32)),
        sa.Column("width", sa.Integer()), sa.Column("height", sa.Integer()), sa.Column("file_size", sa.BigInteger()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_images_kind", "images", ["kind"])
    op.create_table(
        "image_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("image_id", sa.BigInteger(), sa.ForeignKey("images.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("path", sa.Text(), nullable=False),
        sa.Column("normalized_path_digest", sa.BINARY(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.BINARY(32), nullable=False), sa.Column("file_status", sa.String(20), nullable=False),
        sa.Column("archive_date", sa.Date()), sa.Column("ratio_code", sa.String(8)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("normalized_path_digest", name="uq_image_file_path"), mysql_charset="utf8mb4",
    )
    op.create_index("ix_image_files_image_id", "image_files", ["image_id"])
    op.create_table(
        "task_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("image_id", sa.BigInteger(), sa.ForeignKey("images.id")), sa.Column("observed_path", sa.Text(), nullable=False),
        sa.Column("observed_path_digest", sa.BINARY(32), nullable=False), sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("error_code", sa.String(50)), sa.Column("error_message", sa.Text()),
        sa.Column("snapshot_sha256", sa.BINARY(32)), sa.Column("snapshot_size", sa.BigInteger()), sa.Column("snapshot_mtime_ns", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("task_id", "observed_path_digest", name="uq_task_item_path"), mysql_charset="utf8mb4",
    )
    op.create_index("ix_task_items_task_id", "task_items", ["task_id"])
    op.create_table(
        "file_operations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id")), sa.Column("task_item_id", sa.BigInteger(), sa.ForeignKey("task_items.id")), sa.Column("image_id", sa.BigInteger(), sa.ForeignKey("images.id")),
        sa.Column("operation", sa.String(16), nullable=False), sa.Column("origin_path", sa.Text()), sa.Column("target_path", sa.Text()),
        sa.Column("origin_sha256", sa.BINARY(32), nullable=False), sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("operation_key", sa.String(120), nullable=False), sa.Column("state", sa.String(20), nullable=False), sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("thumbnail_path", sa.Text()), sa.Column("error_text", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("operation_key", name="uq_file_operation_key"), mysql_charset="utf8mb4",
    )
    op.create_index("ix_file_operations_task_id", "file_operations", ["task_id"])
    op.create_index("ix_file_operations_task_item_id", "file_operations", ["task_item_id"])
    op.create_index("ix_file_operations_image_id", "file_operations", ["image_id"])


def downgrade() -> None:
    for name in ("ix_file_operations_image_id", "ix_file_operations_task_item_id", "ix_file_operations_task_id"):
        op.drop_index(name, table_name="file_operations")
    op.drop_table("file_operations")
    op.drop_index("ix_task_items_task_id", table_name="task_items")
    op.drop_table("task_items")
    op.drop_index("ix_image_files_image_id", table_name="image_files")
    op.drop_table("image_files")
    op.drop_index("ix_images_kind", table_name="images")
    op.drop_table("images")
