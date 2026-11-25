"""Bind ad hoc and registered research pipelines to immutable versions."""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workflow_definitions", sa.Column("system_kind", sa.String(32)))
    op.create_unique_constraint("workflow_snapshot_kind", "workflow_definitions", ["project_id", "system_kind"])


def downgrade():
    op.drop_constraint("workflow_snapshot_kind", "workflow_definitions", type_="unique")
    op.drop_column("workflow_definitions", "system_kind")
