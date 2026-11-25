"""Persist shared API rate-limit windows."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_rate_limits",
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.CheckConstraint("hits > 0"),
        sa.PrimaryKeyConstraint("bucket_key"),
    )
    op.create_index("api_rate_limits_window", "api_rate_limits", ["window_start"])


def downgrade():
    op.drop_index("api_rate_limits_window", table_name="api_rate_limits")
    op.drop_table("api_rate_limits")