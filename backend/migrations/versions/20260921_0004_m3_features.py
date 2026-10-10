"""M3 persistent feature vectors.

Revision ID: 20260921_0004
Revises: 20260921_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0004"
down_revision = "20260921_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("image_features", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("image_id", sa.BigInteger(), sa.ForeignKey("images.id"), nullable=False), sa.Column("feature_scope", sa.String(28), nullable=False), sa.Column("model_id", sa.String(128), nullable=False), sa.Column("model_revision", sa.String(128), nullable=False), sa.Column("preprocess_version", sa.String(64), nullable=False), sa.Column("dimension", sa.Integer(), nullable=False), sa.Column("vector_blob", sa.LargeBinary(), nullable=False), sa.Column("vector_sha256", sa.BINARY(32), nullable=False), sa.Column("faiss_vector_id", sa.BigInteger()), sa.Column("is_valid", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), mysql_charset="utf8mb4")
    op.create_index("ix_image_features_image_id", "image_features", ["image_id"])
    op.create_index("ix_feature_model_scope", "image_features", ["feature_scope", "model_id", "is_valid"])


def downgrade() -> None:
    op.drop_index("ix_feature_model_scope", table_name="image_features"); op.drop_index("ix_image_features_image_id", table_name="image_features"); op.drop_table("image_features")
