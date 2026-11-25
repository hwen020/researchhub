"""Index event timestamps for bounded operational metric queries."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("job_events_timestamp", "job_events", ["timestamp", "id"])


def downgrade():
    op.drop_index("job_events_timestamp", table_name="job_events")