"""M2 duplicate relationships and reviews.

Revision ID: 20260921_0003
Revises: 20260920_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0003"
down_revision = "20260920_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("duplicate_pairs", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("image_new_id", sa.BigInteger(), sa.ForeignKey("images.id"), nullable=False), sa.Column("image_match_id", sa.BigInteger(), sa.ForeignKey("images.id")), sa.Column("pair_type", sa.String(20), nullable=False), sa.Column("machine_decision", sa.String(32), nullable=False), sa.Column("rule_id", sa.String(80), nullable=False), sa.Column("evidence_json", sa.JSON(), nullable=False), sa.Column("review_required", sa.Boolean(), nullable=False), sa.Column("resolution_status", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), mysql_charset="utf8mb4")
    op.create_index("ix_duplicate_pairs_task_id", "duplicate_pairs", ["task_id"])
    op.create_table("reviews", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("pair_id", sa.BigInteger(), sa.ForeignKey("duplicate_pairs.id"), nullable=False), sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("duplicate_decision", sa.String(24)), sa.Column("action_decision", sa.String(28)), sa.Column("note", sa.Text()), sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.UniqueConstraint("pair_id", name="uq_review_pair"), mysql_charset="utf8mb4")
    op.create_index("ix_reviews_task_id", "reviews", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_reviews_task_id", table_name="reviews"); op.drop_table("reviews")
    op.drop_index("ix_duplicate_pairs_task_id", table_name="duplicate_pairs"); op.drop_table("duplicate_pairs")
