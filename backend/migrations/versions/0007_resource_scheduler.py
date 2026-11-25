"""Add logical quotas, persisted dispatch order and worker capabilities."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    for name, default in (("max_concurrent", 8), ("max_queued", 512),
                          ("quota_cpu", 32), ("quota_memory", 32)):
        op.add_column("projects", sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)))
    op.add_column("projects", sa.Column("last_dispatch", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_check_constraint("projects_positive_quota", "projects",
                               "max_concurrent > 0 AND max_queued > 0 AND quota_cpu > 0 AND quota_memory > 0")
    op.add_column("jobs", sa.Column("capability", sa.String(32), nullable=False, server_default="GENERAL"))
    for name, default in (("cpu_units", 1), ("memory_units", 1), ("priority", 0)):
        op.add_column("jobs", sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)))
    op.execute("UPDATE jobs SET capability = 'GENOMICS' WHERE plugin = 'age-association@1'")
    op.create_check_constraint("jobs_resource_bounds", "jobs",
                               "cpu_units BETWEEN 1 AND 1024 AND memory_units BETWEEN 1 AND 1024 AND priority BETWEEN 0 AND 10")
    op.create_index("jobs_project_state", "jobs", ["project_id", "state"])
    op.add_column("worker_heartbeats", sa.Column("capabilities", sa.JSON(), nullable=False,
                                               server_default='["GENERAL", "GENOMICS"]'))
    for name in ("cpu_units", "memory_units"):
        op.add_column("worker_heartbeats", sa.Column(name, sa.Integer(), nullable=False, server_default="32"))


def downgrade():
    for name in ("capabilities", "cpu_units", "memory_units"):
        op.drop_column("worker_heartbeats", name)
    op.drop_index("jobs_project_state", table_name="jobs")
    op.drop_constraint("jobs_resource_bounds", "jobs", type_="check")
    for name in ("capability", "cpu_units", "memory_units", "priority"):
        op.drop_column("jobs", name)
    op.drop_constraint("projects_positive_quota", "projects", type_="check")
    for name in ("max_concurrent", "max_queued", "quota_cpu", "quota_memory", "last_dispatch"):
        op.drop_column("projects", name)
