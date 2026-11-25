"""Add transactional scientific artifact staging and project storage quotas."""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("storage_quota_bytes", sa.BigInteger(),
                                       server_default="104857600", nullable=False))
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("dataset_version_id", sa.String(36), sa.ForeignKey("dataset_versions.id"), unique=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), unique=True),
        sa.Column("request_key", sa.String(128)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("payload", sa.LargeBinary()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(64)),
        sa.Column("publish_ms", sa.BigInteger()),
        sa.UniqueConstraint("project_id", "request_key"),
        sa.CheckConstraint("size > 0 AND version > 0", name="artifact_size_version"),
        sa.CheckConstraint("state IN ('PENDING','AVAILABLE','FAILED')", name="artifact_state"),
        sa.CheckConstraint(
            "(kind = 'DATASET' AND dataset_version_id IS NOT NULL AND job_id IS NULL) OR "
            "(kind = 'RESULT' AND job_id IS NOT NULL AND dataset_version_id IS NULL)",
            name="artifact_reference_kind",
        ),
    )
    op.create_index("artifacts_publish", "artifacts", ["state", "next_attempt_at", "id"])
    op.create_index("artifacts_project", "artifacts", ["project_id", "created_at"])


def downgrade():
    op.drop_table("artifacts")
    op.drop_column("projects", "storage_quota_bytes")
