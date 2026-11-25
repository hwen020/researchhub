"""Add first-login password rotation and system administration audit."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "system_audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("system_audit_events")
    op.drop_column("users", "must_change_password")