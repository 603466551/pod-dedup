"""M4 region evidence for source-print feature vectors.

Revision ID: 20260921_0005
Revises: 20260921_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0005"
down_revision = "20260921_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_features", sa.Column("region_seq", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("image_features", sa.Column("bbox_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("image_features", "bbox_json")
    op.drop_column("image_features", "region_seq")
