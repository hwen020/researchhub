"""Persist trace associations and workflow timing."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("correlation_id", sa.String(36)))
    op.add_column("jobs", sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id")))
    for name in ("correlation_id", "created_at", "completed_at"):
        field_type = sa.String(36) if name == "correlation_id" else sa.BigInteger()
        op.add_column("workflow_runs", sa.Column(name, field_type))
    op.add_column("artifacts", sa.Column("correlation_id", sa.String(36)))
    op.create_index("workflow_completed_at", "workflow_runs", ["completed_at"])


def downgrade():
    op.drop_index("workflow_completed_at", table_name="workflow_runs")
    op.drop_column("artifacts", "correlation_id")
    for name in ("correlation_id", "created_at", "completed_at"):
        op.drop_column("workflow_runs", name)
    op.drop_column("jobs", "workflow_run_id")
    op.drop_column("jobs", "correlation_id")
