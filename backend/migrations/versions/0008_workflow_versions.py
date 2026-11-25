"""Persist immutable workflow versions, lineage and scheduled triggers."""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("workflow_definitions",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False))
    op.create_index("workflow_definitions_project", "workflow_definitions", ["project_id"])
    op.create_table("workflow_versions",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("definition_id", sa.String(36), sa.ForeignKey("workflow_definitions.id"), nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("definition", sa.JSON(), nullable=False),
                    sa.Column("defaults", sa.JSON(), nullable=False),
                    sa.Column("checksum", sa.String(64), nullable=False),
                    sa.UniqueConstraint("definition_id", "version"))
    op.add_column("workflow_runs", sa.Column("version_id", sa.String(36), sa.ForeignKey("workflow_versions.id")))
    op.add_column("workflow_runs", sa.Column("parent_id", sa.String(36), sa.ForeignKey("workflow_runs.id")))
    op.add_column("workflow_runs", sa.Column("parameters", sa.JSON()))
    op.add_column("workflow_runs", sa.Column("definition_checksum", sa.String(64)))
    runs = sa.table("workflow_runs", sa.column("id"), sa.column("definition", sa.JSON()),
                    sa.column("definition_checksum"))
    connection = op.get_bind()
    last = None
    while True:
        query = sa.select(runs.c.id, runs.c.definition).order_by(runs.c.id).limit(250)
        if last is not None:
            query = query.where(runs.c.id > last)
        batch = connection.execute(query).all()
        if not batch:
            break
        for run_id, definition in batch:
            body = json.dumps(definition, sort_keys=True, allow_nan=False, separators=(",", ":"))
            connection.execute(runs.update().where(runs.c.id == run_id).values(
                definition_checksum=hashlib.sha256(body.encode()).hexdigest(),
            ))
        last = batch[-1].id
    op.alter_column("workflow_runs", "definition_checksum", nullable=False)
    op.create_table("workflow_schedules",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
                    sa.Column("version_id", sa.String(36), sa.ForeignKey("workflow_versions.id"), nullable=False),
                    sa.Column("parameters", sa.JSON(), nullable=False),
                    sa.Column("zone", sa.String(64), nullable=False),
                    sa.Column("next_at", sa.BigInteger()),
                    sa.Column("interval_ms", sa.BigInteger()),
                    sa.Column("last_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id")),
                    sa.Column("last_scheduled_at", sa.BigInteger()))
    op.create_index("workflow_schedules_due", "workflow_schedules", ["next_at", "id"])


def downgrade():
    op.drop_table("workflow_schedules")
    for name in ("definition_checksum", "parameters", "parent_id", "version_id"):
        op.drop_column("workflow_runs", name)
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")
