from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, Column, ForeignKey, Index, Integer,
    MetaData, String, Table, UniqueConstraint,
)

metadata = MetaData()
organizations = Table(
    "organizations", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
)
projects = Table(
    "projects", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), nullable=False),
    Column("name", String(200), nullable=False),
)
users = Table(
    "users", metadata,
    Column("id", String(36), primary_key=True),
    Column("username", String(100), nullable=False, unique=True),
    Column("password_hash", String(256), nullable=False),
    Column("platform_admin", Integer, nullable=False, default=0),
    Column("must_change_password", Integer, nullable=False, default=0),
)
memberships = Table(
    "memberships", metadata,
    Column("project_id", ForeignKey("projects.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("role", String(32), nullable=False),
    CheckConstraint("role IN ('pi', 'researcher', 'finance')"),
)
jobs = Table(
    "jobs", metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("plugin", String(100), nullable=False),
    Column("parameters", JSON, nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("state", String(24), nullable=False),
    Column("attempt", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False),
    Column("timeout_ms", Integer, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("available_at", BigInteger, nullable=False),
    Column("worker", String(100)),
    Column("token", String(36)),
    Column("lease_until", BigInteger),
    Column("deadline", BigInteger),
    Column("result", JSON),
    Column("manifest", JSON),
    Column("provenance", JSON),
    UniqueConstraint("project_id", "idempotency_key"),
    CheckConstraint("attempt >= 0 AND max_attempts BETWEEN 1 AND 8 AND timeout_ms > 0"),
    CheckConstraint("state IN ('QUEUED','RUNNING','RETRYING','SUCCEEDED','FAILED','CANCEL_REQUESTED','CANCELLED')"),
)
Index("jobs_ready", jobs.c.state, jobs.c.available_at)
Index("jobs_lease", jobs.c.state, jobs.c.lease_until)
workers = Table(
    "worker_heartbeats", metadata,
    Column("id", String(100), primary_key=True),
    Column("last_seen", BigInteger, nullable=False, index=True),
)
events = Table(
    "job_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", ForeignKey("jobs.id"), nullable=False, index=True),
    Column("attempt", Integer, nullable=False),
    Column("state", String(24), nullable=False),
    Column("reason", String(64), nullable=False),
    Column("timestamp", BigInteger, nullable=False),
)
Index("job_events_timestamp", events.c.timestamp, events.c.id)
workflow_runs = Table(
    "workflow_runs", metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("node_order", JSON, nullable=False),
    Column("nodes", JSON, nullable=False),
    Column("state", String(24), nullable=False),
    Column("checked_at", BigInteger, nullable=False, default=0),
)
Index("workflow_schedule", workflow_runs.c.state, workflow_runs.c.checked_at)
budgets = Table(
    "budgets", metadata,
    Column("project_id", ForeignKey("projects.id"), primary_key=True),
    Column("limit", BigInteger, nullable=False),
    Column("spent", BigInteger, nullable=False, default=0),
    CheckConstraint('spent >= 0 AND spent <= "limit"'),
)
funding_requests = Table(
    "funding_requests", metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey("budgets.project_id"), nullable=False),
    Column("requester", ForeignKey("users.id"), nullable=False),
    Column("key", String(128), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("purpose", String(300), nullable=False),
    Column("state", String(16), nullable=False),
    Column("reviewer", ForeignKey("users.id")),
    Column("reviewed_at", BigInteger),
    CheckConstraint("amount > 0"),
    CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')"),
    UniqueConstraint("project_id", "key"),
)
datasets = Table(
    "datasets", metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False, index=True),
    Column("owner_id", ForeignKey("users.id"), nullable=False),
    Column("name", String(200), nullable=False),
)
versions = Table(
    "dataset_versions", metadata,
    Column("id", String(36), primary_key=True),
    Column("dataset_id", ForeignKey("datasets.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("size", Integer, nullable=False),
    UniqueConstraint("dataset_id", "version"),
)
audit = Table(
    "audit_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project_id", ForeignKey("projects.id"), nullable=False, index=True),
    Column("actor_id", ForeignKey("users.id"), nullable=False),
    Column("action", String(40), nullable=False),
    Column("subject_id", String(36), nullable=False),
    Column("timestamp", BigInteger, nullable=False),
)
system_audit = Table(
    "system_audit_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor_id", ForeignKey("users.id"), nullable=False),
    Column("action", String(40), nullable=False),
    Column("subject_id", String(36), nullable=False),
    Column("timestamp", BigInteger, nullable=False),
)
api_rate_limits = Table(
    "api_rate_limits", metadata,
    Column("bucket_key", String(64), primary_key=True),
    Column("window_start", BigInteger, nullable=False),
    Column("hits", Integer, nullable=False),
    CheckConstraint("hits > 0"),
)
Index("api_rate_limits_window", api_rate_limits.c.window_start)

