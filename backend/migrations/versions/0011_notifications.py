"""Add persistent project notification delivery and read receipts."""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("correlation_id", sa.String(36)),
        sa.Column("published_sequence", sa.BigInteger(), unique=True),
        sa.UniqueConstraint("kind", "subject_id"),
    )
    op.create_index("notifications_feed", "notifications", ["project_id", "published_sequence"])
    op.create_table(
        "notification_receipts",
        sa.Column("notification_id", sa.String(36), sa.ForeignKey("notifications.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("read_at", sa.BigInteger(), nullable=False),
    )


def downgrade():
    op.drop_table("notification_receipts")
    op.drop_table("notifications")
