"""Persist run manifests, dataset provenance and project audit events."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("manifest", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("provenance", sa.JSON(), nullable=True))
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])


def downgrade():
    op.drop_index("ix_audit_events_project_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_column("jobs", "provenance")
    op.drop_column("jobs", "manifest")
