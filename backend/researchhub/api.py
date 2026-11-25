import csv
import time
import hashlib
import hmac
import io
import json
import os
import secrets
import threading
from collections import Counter, deque
from pathlib import Path
from typing import Dict, List, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from .artifacts import ArtifactUnavailable, StorageQuotaExceeded, get_bytes, publish as publish_artifact
from .artifacts import quota_lock as storage_quota_lock
from .artifacts import usage as storage_usage
from .auth import hash_password, require_project, verify_password
from .db import connect
from .finance import decide, request_funds
from .demo_fixture import GUEST_ID, PROJECT_ID
from .models import api_rate_limits, artifacts, audit, budgets, datasets, events, funding_requests, jobs, memberships, organizations, projects, system_audit, users, versions, workers, workflow_runs
from .plugins import validate_parameters
from .queue import IdempotencyConflict, cancel, now_ms, submit
from .resource_policy import (
    ACTIVE, READY, QUOTA_FIELDS, QueueFull, online_workers, project_usage,
    scheduling_lock, system_limit, wait_reason,
)
from . import notifications as project_notifications
from .observability import emit, prometheus_text, request_id, runtime_snapshot
from .registry import MAX_UPLOAD, compute_inputs, download, register, stage_upload
from .research_workflows import start_research
from .storage import LocalStorage, managed_storage
from . import provenance as run_provenance
from .models import workflow_definitions, workflow_schedules, workflow_versions
from .workflow_versions import create_schedule, publish, start_version
from .workflows import cancel_run, rerun, start

app = FastAPI(title="ResearchHub")
engine = connect()
security = HTTPBasic(auto_error=False)
dummy_hash = hash_password(uuid4().hex)
ALL_ROLES = {"pi", "researcher", "finance"}
COMPUTE_ROLES = {"pi", "researcher"}
AUTH_FAILURE_LIMIT = 10
AUTH_FAILURE_WINDOW_MS = 300_000
AUTH_SOURCE_FAILURE_LIMIT = 60
JOB_SUBMISSION_LIMIT = 120
WORKFLOW_SUBMISSION_LIMIT = 30
DATASET_UPLOAD_LIMIT = 20
API_RATE_WINDOW_MS = 60_000
METRICS_EVENT_WINDOW_MS = 86_400_000
METRICS_EVENT_LIMIT = 20_000
HTTP_METRICS_SAMPLE_LIMIT = 5_000
_rate_cleanup_lock = threading.Lock()
_last_rate_cleanup_ms = 0
_http_metrics_lock = threading.Lock()
_http_duration_samples = deque(maxlen=HTTP_METRICS_SAMPLE_LIMIT)
_http_status_classes = Counter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RequestMetricsMiddleware:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in {"/metrics", "/metrics/prometheus"}:
            await self.application(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500
        trace_id = str(uuid4())
        trace_token = request_id.set(trace_id)

        async def record_response(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", trace_id.encode()))
            await send(message)

        try:
            await self.application(scope, receive, record_response)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            with _http_metrics_lock:
                _http_duration_samples.append(elapsed_ms)
                _http_status_classes[f"{status_code // 100}xx"] += 1
            request_id.reset(trace_token)
            if scope.get("path") not in {"/healthz", "/readyz"}:
                emit("http_request", correlation_id=trace_id, method=scope["method"],
                     route=getattr(scope.get("route"), "path", None), status=status_code,
                     duration_ms=round(elapsed_ms, 2))


app.add_middleware(RequestMetricsMiddleware)


@app.exception_handler(ArtifactUnavailable)
async def unavailable_artifact(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "2"})


class DatasetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    version: int = Field(ge=1, strict=True)


class JobInput(RequestModel):
    plugin: Literal["summary@1", "age-association@1"]
    parameters: dict | None = None
    dataset: DatasetReference | None = None
    timeout_ms: int = Field(30_000, ge=1000, le=300_000)
    max_attempts: int = Field(3, ge=1, le=8)
    capability: Literal["GENERAL", "GENOMICS", "GEOSPATIAL", "HIGH_MEMORY"] | None = None
    cpu_units: int = Field(1, ge=1, le=1024)
    memory_units: int = Field(1, ge=1, le=1024)
    priority: int = Field(0, ge=0, le=10)


class ResourceQuotaInput(RequestModel):
    max_concurrent: int = Field(ge=1, le=1024)
    max_queued: int = Field(ge=1, le=10000)
    quota_cpu: int = Field(ge=1, le=100000)
    quota_memory: int = Field(ge=1, le=100000)
    storage_quota_bytes: int | None = Field(None, ge=1, le=10**12)


class DependencyCondition(RequestModel):
    mode: Literal["success", "failure", "always", "result_equals"]
    node: str | None = Field(None, max_length=64)
    field: str | None = Field(None, max_length=64)
    value: str | int | float | bool | None = None


class NodeInput(RequestModel):
    plugin: Literal["summary@1", "age-association@1"]
    parameters: dict | None = None
    dataset: DatasetReference | None = None
    depends_on: List[str] = Field(default_factory=list, max_length=64)
    when: DependencyCondition | None = None


class WorkflowInput(RequestModel):
    nodes: Dict[str, NodeInput] = Field(min_length=1, max_length=64)


class WorkflowVersionInput(WorkflowInput):
    defaults: dict = Field(default_factory=dict, max_length=64)


class WorkflowTemplateInput(WorkflowVersionInput):
    name: str = Field(min_length=1, max_length=120)


class WorkflowParameters(RequestModel):
    parameters: dict = Field(default_factory=dict, max_length=64)


class WorkflowScheduleInput(WorkflowParameters):
    start_at: str = Field(max_length=40)
    zone: str = Field(min_length=1, max_length=64)
    interval_seconds: int | None = Field(None, ge=60, le=31_536_000)


class ResearchWorkflowInput(RequestModel):
    discipline: Literal["genomics", "mobility"]
    dataset: DatasetReference
    timezone: str = Field("UTC", min_length=1, max_length=64)


class WorkflowRerunInput(RequestModel):
    failed_node: str | None = Field(None, min_length=1, max_length=64)


def prepare_workflow(connection, project, nodes, *, template=False):
    definition = {}
    for name, node in nodes.items():
        spec = node.model_dump(exclude={"dataset", "when"})
        if node.when is not None:
            spec["when"] = node.when.model_dump(exclude_unset=True)
        if (node.parameters is None) == (node.dataset is None):
            raise ValueError("Each node must provide parameters or a dataset version")
        if node.dataset is not None:
            spec["parameters"], spec["provenance"] = compute_inputs(
                connection, storage(), project, str(node.dataset.id), node.dataset.version, node.plugin,
            )
        if not template or node.dataset is not None:
            spec["parameters"] = validate_parameters(node.plugin, spec["parameters"])
        definition[name] = spec
    return definition


class NotificationReadInput(RequestModel):
    read: bool


class AnnouncementInput(RequestModel):
    message: str = Field(min_length=1, max_length=500)


class FundingInput(RequestModel):
    amount: int = Field(ge=1, le=10**12)
    purpose: str = Field(min_length=1, max_length=300)


class DecisionInput(RequestModel):
    approve: bool


class DatasetInput(RequestModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectInput(RequestModel):
    organization_id: UUID = Field(strict=False)
    name: str = Field(min_length=1, max_length=200)
    budget_limit: int = Field(ge=0, le=10**12)


class AccountInput(RequestModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class MembershipInput(RequestModel):
    username: str = Field(min_length=3, max_length=100)
    role: Literal["pi", "researcher", "finance"]


class MemberRoleInput(RequestModel):
    role: Literal["pi", "researcher", "finance"]


class PasswordInput(RequestModel):
    password: str = Field(min_length=12, max_length=256)


def transaction():
    try:
        with engine.begin() as connection:
            yield connection
    except OperationalError as exc:
        raise HTTPException(503, "Database unavailable") from exc


def rate_bucket(scope, identity):
    secret = engine.url.password or "researchhub-rate-limit"
    return hmac.new(secret.encode(), (scope + ":" + identity).encode(), hashlib.sha256).hexdigest()


def rate_limited(window_ms, timestamp=None):
    if timestamp is None:
        with engine.connect() as rate_connection:
            timestamp = now_ms(rate_connection)
    window_start = timestamp - timestamp % window_ms
    seconds = max(1, (window_start + window_ms - timestamp + 999) // 1000)
    return HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(seconds)})


def check_rate_limit(scope, identity, limit, window_ms):
    try:
        with engine.connect() as rate_connection:
            timestamp = now_ms(rate_connection)
            window_start = timestamp - timestamp % window_ms
            count = rate_connection.execute(select(api_rate_limits.c.hits).where(
                api_rate_limits.c.bucket_key == rate_bucket(scope, identity),
                api_rate_limits.c.window_start == window_start,
            )).scalar_one_or_none() or 0
    except OperationalError as exc:
        raise HTTPException(503, "Database unavailable") from exc
    if count >= limit:
        raise rate_limited(window_ms, timestamp)


def record_rate_limit(scope, identity, limit, window_ms):
    global _last_rate_cleanup_ms
    try:
        with engine.begin() as rate_connection:
            timestamp = now_ms(rate_connection)
            window_start = timestamp - timestamp % window_ms
            count = rate_connection.execute(pg_insert(api_rate_limits).values(
                bucket_key=rate_bucket(scope, identity), window_start=window_start, hits=1,
            ).on_conflict_do_update(
                index_elements=[api_rate_limits.c.bucket_key],
                set_={
                    "window_start": window_start,
                    "hits": case(
                        (api_rate_limits.c.window_start == window_start,
                         func.least(api_rate_limits.c.hits + 1, limit + 1)),
                        else_=1,
                    ),
                },
            ).returning(api_rate_limits.c.hits)).scalar_one()
            with _rate_cleanup_lock:
                if timestamp - _last_rate_cleanup_ms >= 60_000:
                    rate_connection.execute(delete(api_rate_limits).where(
                        api_rate_limits.c.window_start < timestamp - 86_400_000,
                    ))
                    _last_rate_cleanup_ms = timestamp
    except OperationalError as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return count


def enforce_rate_limit(scope, identity, limit, window_ms):
    if record_rate_limit(scope, identity, limit, window_ms) > limit:
        raise rate_limited(window_ms)


def distribution(samples):
    ordered = sorted(samples)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    return {
        "count": len(ordered),
        "p50": round(ordered[(len(ordered) - 1) // 2], 3),
        "p95": round(ordered[min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def job_event_metrics(connection, timestamp):
    rows = connection.execute(select(
        events.c.job_id, events.c.attempt, events.c.state, events.c.timestamp,
    ).where(events.c.timestamp >= timestamp - METRICS_EVENT_WINDOW_MS)
        .order_by(events.c.timestamp.desc(), events.c.id.desc())
        .limit(METRICS_EVENT_LIMIT)).mappings().all()
    queued_at = {}
    running_at = {}
    queue_waits = []
    execution_times = []
    for event in reversed(rows):
        job_id = event["job_id"]
        attempt = event["attempt"]
        state = event["state"]
        event_time = event["timestamp"]
        if state in {"QUEUED", "RETRYING"}:
            queued_at[job_id] = event_time
        if state == "RUNNING":
            previous = queued_at.pop(job_id, None)
            if previous is not None and event_time >= previous:
                queue_waits.append(event_time - previous)
            running_at[(job_id, attempt)] = event_time
        if state in {"SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"}:
            started = running_at.pop((job_id, attempt), None)
            if started is not None and event_time >= started:
                execution_times.append(event_time - started)
    return distribution(queue_waits), distribution(execution_times)


def authenticate(request: Request, credentials: HTTPBasicCredentials | None = Depends(security), connection=Depends(transaction, scope="function")):
    user = None
    password = "missing credential"
    if credentials is not None:
        source = request.client.host if request.client else "unknown"
        account_key = credentials.username.casefold()
        check_rate_limit("auth_account_failure", account_key, AUTH_FAILURE_LIMIT, AUTH_FAILURE_WINDOW_MS)
        check_rate_limit("auth_source_failure", source, AUTH_SOURCE_FAILURE_LIMIT, AUTH_FAILURE_WINDOW_MS)
        user = connection.execute(select(users).where(users.c.username == credentials.username[:101])).mappings().one_or_none()
        password = credentials.password
    if not verify_password(password, user["password_hash"] if user else dummy_hash) or user is None:
        if credentials is not None:
            account_hits = record_rate_limit("auth_account_failure", account_key, AUTH_FAILURE_LIMIT, AUTH_FAILURE_WINDOW_MS)
            source_hits = record_rate_limit("auth_source_failure", source, AUTH_SOURCE_FAILURE_LIMIT, AUTH_FAILURE_WINDOW_MS)
            if account_hits > AUTH_FAILURE_LIMIT or source_hits > AUTH_SOURCE_FAILURE_LIMIT:
                raise rate_limited(AUTH_FAILURE_WINDOW_MS)
        raise HTTPException(401, "Invalid credentials")
    if os.getenv("RESEARCHHUB_DEMO_MODE") == "1":
        if user["id"] != GUEST_ID or user["platform_admin"]:
            raise HTTPException(401, "Invalid credentials")
        if request.method not in {"GET", "HEAD"}:
            raise HTTPException(403, "The public demo runs a fixed synthetic workflow")
    if user["must_change_password"] and request.url.path not in {"/auth/status", "/auth/password"}:
        raise HTTPException(403, "Password change required")
    if request.method == "POST":
        parts = request.url.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "jobs":
            enforce_rate_limit("job_submission", user["id"], JOB_SUBMISSION_LIMIT, API_RATE_WINDOW_MS)
        elif len(parts) == 3 and parts[0] == "projects" and parts[2] == "workflows":
            enforce_rate_limit("workflow_submission", user["id"], WORKFLOW_SUBMISSION_LIMIT, API_RATE_WINDOW_MS)
        elif len(parts) == 5 and parts[0] == "projects" and parts[2] == "datasets" and parts[4] == "versions":
            enforce_rate_limit("dataset_upload", user["id"], DATASET_UPLOAD_LIMIT, API_RATE_WINDOW_MS)
    return user


def authorize(connection, user, project_id, roles):
    if os.getenv("RESEARCHHUB_DEMO_MODE") == "1" and project_id != PROJECT_ID:
        raise HTTPException(404, "Project not found")
    if connection.execute(select(projects.c.id).where(projects.c.id == project_id)).scalar_one_or_none() is None:
        raise HTTPException(404, "Project not found")
    try:
        require_project(connection, user["id"], project_id, roles)
    except PermissionError as exc:
        raise HTTPException(404, "Project not found") from exc


def public_job(job):
    return {key: job[key] for key in (
        "id", "state", "plugin", "attempt", "created_at", "result",
        "capability", "cpu_units", "memory_units", "priority",
    )}


def log_action(connection, user, project, action, subject):
    connection.execute(audit.insert().values(
        project_id=project, actor_id=user["id"], action=action,
        subject_id=subject, timestamp=now_ms(connection),
    ))


def log_system_action(connection, user, action, subject):
    connection.execute(system_audit.insert().values(
        actor_id=user["id"], action=action, subject_id=subject,
        timestamp=now_ms(connection),
    ))


def require_admin(user):
    if not user["platform_admin"]:
        raise HTTPException(403, "Platform administrator required")


@app.get("/auth/status")
def auth_status(user=Depends(authenticate)):
    return {"platform_admin": bool(user["platform_admin"]),
            "must_change_password": bool(user["must_change_password"]),
            "demo_mode": os.getenv("RESEARCHHUB_DEMO_MODE") == "1"}


@app.post("/auth/password")
def change_password(body: PasswordInput, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    connection.execute(users.update().where(users.c.id == user["id"]).values(
        password_hash=hash_password(body.password), must_change_password=0,
    ))
    log_system_action(connection, user, "password_changed", user["id"])
    return {"must_change_password": False}


@app.get("/admin/organizations")
def admin_organizations(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    require_admin(user)
    query = select(organizations.c.id, organizations.c.name).order_by(organizations.c.name)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.post("/admin/projects")
def admin_create_project(body: ProjectInput, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    require_admin(user)
    organization_id = str(body.organization_id)
    if connection.execute(select(organizations.c.id).where(organizations.c.id == organization_id)).scalar_one_or_none() is None:
        raise HTTPException(404, "Organization not found")
    duplicate = connection.execute(select(projects.c.id).where(
        projects.c.organization_id == organization_id, projects.c.name == body.name,
    )).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(409, "Project already exists")
    project_id = str(uuid4())
    connection.execute(projects.insert().values(
        id=project_id, organization_id=organization_id, name=body.name,
    ))
    connection.execute(budgets.insert().values(project_id=project_id, limit=body.budget_limit, spent=0))
    log_action(connection, user, project_id, "project_created", project_id)
    return {"id": project_id, "name": body.name}


@app.post("/admin/accounts")
def admin_create_account(body: AccountInput, response: Response,
                         user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    require_admin(user)
    account_id = str(uuid4())
    temporary_password = secrets.token_urlsafe(24)
    inserted = connection.execute(pg_insert(users).values(
        id=account_id, username=body.username, password_hash=hash_password(temporary_password),
        platform_admin=0, must_change_password=1,
    ).on_conflict_do_nothing(index_elements=[users.c.username])).rowcount
    if not inserted:
        raise HTTPException(409, "Username already exists")
    log_system_action(connection, user, "account_created", account_id)
    response.headers["Cache-Control"] = "no-store"
    return {"username": body.username, "temporary_password": temporary_password}


@app.get("/admin/audit")
def admin_audit(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    require_admin(user)
    query = select(system_audit).order_by(system_audit.c.id.desc()).limit(100)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.get("/projects/{project_id}/members")
def project_members(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi"})
    query = select(users.c.username, memberships.c.role).join(
        memberships, memberships.c.user_id == users.c.id,
    ).where(memberships.c.project_id == project).order_by(users.c.username)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.post("/projects/{project_id}/members")
def add_project_member(project_id: UUID, body: MembershipInput, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi"})
    if body.role == "pi" and not user["platform_admin"]:
        raise HTTPException(403, "Only a platform administrator can grant PI role")
    member = connection.execute(select(users.c.id).where(users.c.username == body.username)).scalar_one_or_none()
    if member is None:
        raise HTTPException(404, "Account not found")
    if member == user["id"] and not user["platform_admin"]:
        raise HTTPException(403, "Cannot add yourself as a project member")
    inserted = connection.execute(pg_insert(memberships).values(
        project_id=project, user_id=member, role=body.role,
    ).on_conflict_do_nothing(index_elements=[memberships.c.project_id, memberships.c.user_id])).rowcount
    if not inserted:
        raise HTTPException(409, "Account is already a project member")
    log_action(connection, user, project, "membership_added", member)
    return {"username": body.username, "role": body.role}


@app.patch("/projects/{project_id}/members/{username}")
def update_project_member(project_id: UUID, username: str, body: MemberRoleInput,
                          user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi"})
    connection.execute(select(projects.c.id).where(projects.c.id == project).with_for_update()).scalar_one()
    member = connection.execute(select(users.c.id, memberships.c.role).join(
        memberships, memberships.c.user_id == users.c.id,
    ).where(memberships.c.project_id == project, users.c.username == username).with_for_update()).mappings().one_or_none()
    if member is None:
        raise HTTPException(404, "Project member not found")
    if not user["platform_admin"] and (member["id"] == user["id"] or member["role"] == "pi" or body.role == "pi"):
        raise HTTPException(403, "Project PI role changes require a platform administrator")
    if member["role"] == "pi" and body.role != "pi":
        pi_count = connection.execute(select(func.count()).select_from(memberships).where(
            memberships.c.project_id == project, memberships.c.role == "pi",
        )).scalar_one()
        if pi_count <= 1:
            raise HTTPException(409, "A project must retain at least one PI")
    connection.execute(memberships.update().where(
        memberships.c.project_id == project, memberships.c.user_id == member["id"],
    ).values(role=body.role))
    log_action(connection, user, project, "membership_role_changed", member["id"])
    return {"username": username, "role": body.role}


@app.delete("/projects/{project_id}/members/{username}")
def remove_project_member(project_id: UUID, username: str,
                          user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi"})
    connection.execute(select(projects.c.id).where(projects.c.id == project).with_for_update()).scalar_one()
    member = connection.execute(select(users.c.id, memberships.c.role).join(
        memberships, memberships.c.user_id == users.c.id,
    ).where(memberships.c.project_id == project, users.c.username == username).with_for_update()).mappings().one_or_none()
    if member is None:
        raise HTTPException(404, "Project member not found")
    if not user["platform_admin"] and (member["id"] == user["id"] or member["role"] == "pi"):
        raise HTTPException(403, "Project PI membership changes require a platform administrator")
    if member["role"] == "pi":
        pi_count = connection.execute(select(func.count()).select_from(memberships).where(
            memberships.c.project_id == project, memberships.c.role == "pi",
        )).scalar_one()
        if pi_count <= 1:
            raise HTTPException(409, "A project must retain at least one PI")
    connection.execute(memberships.delete().where(
        memberships.c.project_id == project, memberships.c.user_id == member["id"],
    ))
    log_action(connection, user, project, "membership_removed", member["id"])
    return {"removed": username}


@app.get("/projects/{project_id}/audit")
def project_audit(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi", "finance"})
    query = select(audit).where(audit.c.project_id == project).order_by(audit.c.id.desc()).limit(100)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.get("/projects/{project_id}/jobs/{job_id}/download/{kind}")
def download_job(project_id: UUID, job_id: UUID, kind: Literal["manifest", "json", "csv", "geojson"],
                 user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    row = connection.execute(select(jobs.c.manifest, jobs.c.result).where(
        jobs.c.project_id == project, jobs.c.id == str(job_id), jobs.c.state == "SUCCEEDED",
    )).mappings().one_or_none()
    if row is None or (kind == "manifest" and row["manifest"] is None):
        raise HTTPException(404, "Artifact not available")
    filename = "manifest.json" if kind == "manifest" else "result." + kind
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    if os.getenv("RESEARCHHUB_DEMO_MODE") != "1":
        log_action(connection, user, project, "job_artifact_download", str(job_id))
    result = row["result"]
    if kind != "manifest" and row["manifest"] and row["manifest"].get("output_artifact_id"):
        artifact_id = row["manifest"]["output_artifact_id"]
        adapter = managed_storage()
        publish_artifact(connection, adapter, now_ms(connection), artifact_id)
        artifact = connection.execute(select(artifacts).where(
            artifacts.c.project_id == project, artifacts.c.id == artifact_id,
        )).mappings().one()
        result = json.loads(get_bytes(adapter, artifact))
    if kind == "geojson":
        if "geojson" not in result:
            raise HTTPException(404, "GeoJSON is unavailable for this job")
        return JSONResponse(result["geojson"], media_type="application/geo+json", headers=headers)
    if kind != "csv":
        return JSONResponse(row["manifest"] if kind == "manifest" else result, headers=headers)
    records = result.get("associations", result.get("records", [result]))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    return Response(stream.getvalue(), media_type="text/csv", headers=headers)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready(connection=Depends(transaction, scope="function")):
    connection.execute(select(jobs.c.id, jobs.c.manifest).limit(1))
    connection.execute(select(workers.c.id).limit(1))
    return {"status": "ready"}


@app.get("/metrics")
def metrics(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    if not user["platform_admin"]:
        raise HTTPException(403, "Platform administrator required")
    counts = connection.execute(select(jobs.c.state, func.count()).group_by(jobs.c.state))
    states = dict(counts.all())
    active = connection.execute(select(func.count()).select_from(workers).where(
        workers.c.last_seen > now_ms(connection) - 10_000,
    )).scalar_one()
    retries = connection.execute(select(func.count()).select_from(events).where(
        events.c.state == "RETRYING",
    )).scalar_one()
    timestamp = now_ms(connection)
    queue_wait, execution = job_event_metrics(connection, timestamp)
    with _http_metrics_lock:
        http_durations = list(_http_duration_samples)
        http_status_classes = dict(_http_status_classes)
    return {"jobs_by_state": states, "workers_online": active, "retries": retries,
            "queue_depth": states.get("QUEUED", 0) + states.get("RETRYING", 0),
            "queue_capacity": system_limit(),
            "queue_saturation": sum(states.get(state, 0) for state in ACTIVE + READY) / system_limit(),
            "job_queue_wait_ms": queue_wait,
            "job_execution_ms": execution,
            "job_metrics_window": {"hours": 24, "max_events": METRICS_EVENT_LIMIT},
            **runtime_snapshot(connection, timestamp, distribution),
            "http_requests": {
                "status_classes": http_status_classes,
                "duration_ms": distribution(http_durations),
                "sample_limit": HTTP_METRICS_SAMPLE_LIMIT,
                "scope": "per API process; last 5000 completed requests",
            }}


@app.get("/metrics/prometheus")
def prometheus_metrics(request: Request, credentials: HTTPBasicCredentials | None = Depends(security),
                       connection=Depends(transaction, scope="function")):
    token_path = os.getenv("RESEARCHHUB_METRICS_TOKEN_FILE")
    supplied = request.headers.get("authorization", "").encode("utf-8")
    token = Path(token_path).read_bytes().strip() if token_path else b""
    if token and hmac.compare_digest(supplied, b"Bearer " + token):
        user = {"platform_admin": True}
    else:
        user = authenticate(request, credentials, connection)
    return Response(prometheus_text(metrics(user, connection)), media_type="text/plain; version=0.0.4")


@app.get("/projects")
def list_projects(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    query = select(projects.c.id, projects.c.name, organizations.c.name.label("organization")).join(organizations)
    if not user["platform_admin"]:
        query = query.join(memberships, memberships.c.project_id == projects.c.id).where(
            memberships.c.user_id == user["id"],
        ).add_columns(memberships.c.role)
    else:
        query = query.add_columns(literal("platform_admin").label("role"))
    if os.getenv("RESEARCHHUB_DEMO_MODE") == "1":
        query = query.where(projects.c.id == PROJECT_ID)
    return [dict(row) for row in connection.execute(query.order_by(projects.c.name, projects.c.id)).mappings()]


@app.get("/projects/{project_id}/resources")
def get_resources(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    quota = connection.execute(select(*(projects.c[field] for field in QUOTA_FIELDS), projects.c.storage_quota_bytes).where(
        projects.c.id == project,
    )).mappings().one()
    return {"quota": dict(quota), "usage": project_usage(connection, project),
            "storage_bytes": storage_usage(connection, project)}


@app.put("/projects/{project_id}/resources")
def update_resources(project_id: UUID, body: ResourceQuotaInput, user=Depends(authenticate),
                     connection=Depends(transaction, scope="function")):
    project = str(project_id)
    require_admin(user)
    scheduling_lock(connection)
    storage_quota_lock(connection, project)
    quota = body.model_dump(exclude_none=True)
    usage = project_usage(connection, project)
    if body.storage_quota_bytes is not None and body.storage_quota_bytes < storage_usage(connection, project):
        raise HTTPException(409, "Storage quota would be lower than reserved bytes")
    oversized = connection.execute(select(jobs.c.id).where(
        jobs.c.project_id == project, jobs.c.state.in_(ACTIVE + READY),
        (jobs.c.cpu_units > body.quota_cpu) | (jobs.c.memory_units > body.quota_memory),
    ).limit(1)).first()
    if (oversized or usage["active"] > body.max_concurrent
            or usage["active"] + usage["queued"] > body.max_queued
            or usage["cpu_units"] > body.quota_cpu or usage["memory_units"] > body.quota_memory):
        raise HTTPException(409, "Quota would invalidate outstanding work")
    updated = connection.execute(projects.update().where(projects.c.id == project).values(**quota))
    if not updated.rowcount:
        raise HTTPException(404, "Project not found")
    log_system_action(connection, user, "project_quota_updated", project)
    return {"quota": quota, "usage": usage}


@app.get("/admin/workers")
def list_workers(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    require_admin(user)
    return [dict(worker) for worker in online_workers(connection, now_ms(connection))]


@app.post("/projects/{project_id}/jobs")
def submit_job(project_id: UUID, body: JobInput,
               key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
               user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    if key.startswith("dag:"):
        raise HTTPException(422, "Reserved idempotency prefix")
    if (body.parameters is None) == (body.dataset is None):
        raise HTTPException(422, "Provide either parameters or a dataset version")
    try:
        parameters, provenance = body.parameters, None
        if body.dataset is not None:
            parameters, provenance = compute_inputs(
                connection, storage(), project, str(body.dataset.id), body.dataset.version, body.plugin,
            )
        parameters = validate_parameters(body.plugin, parameters)
        job = submit(connection, project, key, body.plugin, parameters,
                     max_attempts=body.max_attempts, timeout_ms=body.timeout_ms, provenance=provenance,
                     capability=body.capability, cpu_units=body.cpu_units,
                     memory_units=body.memory_units, priority=body.priority)
    except LookupError as exc:
        raise HTTPException(404, "Dataset version not found") from exc
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "1"}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "job_submission", job["id"])
    return public_job(job)


@app.get("/projects/{project_id}/jobs")
def project_jobs(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(jobs).where(jobs.c.project_id == project).order_by(jobs.c.created_at.desc(), jobs.c.id).limit(100)
    rows = connection.execute(query).mappings().all()
    quota = connection.execute(select(projects).where(projects.c.id == project)).mappings().one()
    usage = project_usage(connection, project)
    timestamp = now_ms(connection)
    eligible_workers = online_workers(connection, timestamp)
    return [dict(public_job(row), wait_reason=wait_reason(row, quota, usage, eligible_workers, timestamp)
                 if row["state"] in READY else None) for row in rows]


@app.get("/projects/{project_id}/jobs/{job_id}/events")
def job_events(project_id: UUID, job_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    exists = connection.execute(select(jobs.c.id).where(jobs.c.project_id == project, jobs.c.id == str(job_id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, "Job not found")
    query = select(events).where(events.c.job_id == str(job_id)).order_by(events.c.id)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.post("/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(project_id: UUID, job_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        state = cancel(connection, project, str(job_id))
    except LookupError as exc:
        raise HTTPException(404, "Job not found") from exc
    log_action(connection, user, project, "job_cancellation", str(job_id))
    return {"state": state}


@app.post("/projects/{project_id}/workflows")
def start_workflow(project_id: UUID, body: WorkflowInput, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        run_id = start(connection, project, prepare_workflow(connection, project, body.nodes))
    except LookupError as exc:
        raise HTTPException(404, "Dataset version not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "workflow_started", run_id)
    return {"id": run_id}


@app.get("/projects/{project_id}/workflows")
def list_workflows(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(workflow_runs.c.id, workflow_runs.c.state, workflow_runs.c.nodes,
                   workflow_runs.c.version_id, workflow_runs.c.parent_id,
                   workflow_runs.c.definition_checksum, workflow_runs.c.definition).where(
        workflow_runs.c.project_id == project,
    ).order_by(workflow_runs.c.checked_at.desc(), workflow_runs.c.id).limit(100)
    return [{**{key: value for key, value in row.items() if key != "definition"},
             "dependencies": {name: spec["depends_on"] for name, spec in row["definition"].items()},
             "conditions": {name: spec["when"] for name, spec in row["definition"].items() if spec.get("when")}}
            for row in connection.execute(query).mappings()]


@app.post("/projects/{project_id}/research-workflows")
def run_research_workflow(project_id: UUID, body: ResearchWorkflowInput, user=Depends(authenticate),
                          connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    enforce_rate_limit("workflow_submission", user["id"], WORKFLOW_SUBMISSION_LIMIT, API_RATE_WINDOW_MS)
    try:
        run_id = start_research(connection, storage(), project, str(body.dataset.id), body.dataset.version,
                                body.discipline, body.timezone)
    except LookupError as exc:
        raise HTTPException(404, "Dataset version not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "research_workflow_started", run_id)
    return {"id": run_id}


@app.get("/projects/{project_id}/workflow-templates")
def list_templates(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(workflow_definitions).where(workflow_definitions.c.project_id == project,
                                                workflow_definitions.c.system_kind.is_(None))
    return [dict(row) for row in connection.execute(query.order_by(workflow_definitions.c.name,
                                                                  workflow_definitions.c.id)).mappings()]


@app.get("/projects/{project_id}/workflow-templates/{template_id}/versions")
def list_workflow_versions(project_id: UUID, template_id: UUID, user=Depends(authenticate),
                           connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(workflow_versions).join(workflow_definitions).where(
        workflow_definitions.c.project_id == project, workflow_definitions.c.id == str(template_id),
        workflow_definitions.c.system_kind.is_(None),
    ).order_by(workflow_versions.c.version.desc())
    return [dict(row) for row in connection.execute(query).mappings()]


def publish_template(connection, user, project, body, **template):
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        definition = prepare_workflow(connection, project, body.nodes, template=True)
        version = publish(connection, project, definition, body.defaults, **template)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "workflow_version_published", version["id"])
    return version


@app.post("/projects/{project_id}/workflow-templates")
def create_template(project_id: UUID, body: WorkflowTemplateInput, user=Depends(authenticate),
                    connection=Depends(transaction, scope="function")):
    return publish_template(connection, user, str(project_id), body, name=body.name)


@app.post("/projects/{project_id}/workflow-templates/{template_id}/versions")
def add_workflow_version(project_id: UUID, template_id: UUID, body: WorkflowVersionInput,
                         user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    return publish_template(connection, user, str(project_id), body, definition_id=str(template_id))


@app.post("/projects/{project_id}/workflow-versions/{version_id}/runs")
def run_workflow_version(project_id: UUID, version_id: UUID, body: WorkflowParameters,
                         user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        run_id = start_version(connection, project, str(version_id), body.parameters)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "workflow_started", run_id)
    return {"id": run_id}


@app.get("/projects/{project_id}/workflow-schedules")
def list_schedules(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(workflow_schedules).where(workflow_schedules.c.project_id == project)
    return [dict(row) for row in connection.execute(query.order_by(workflow_schedules.c.next_at,
                                                                  workflow_schedules.c.id)).mappings()]


@app.post("/projects/{project_id}/workflow-versions/{version_id}/schedules")
def schedule_workflow(project_id: UUID, version_id: UUID, body: WorkflowScheduleInput,
                      user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        schedule = create_schedule(connection, project, str(version_id), body.parameters, body.start_at,
                                   body.zone, body.interval_seconds)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "workflow_scheduled", schedule["id"])
    return schedule


@app.delete("/projects/{project_id}/workflow-schedules/{schedule_id}")
def stop_schedule(project_id: UUID, schedule_id: UUID, user=Depends(authenticate),
                  connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    updated = connection.execute(workflow_schedules.update().where(
        workflow_schedules.c.project_id == project, workflow_schedules.c.id == str(schedule_id),
    ).values(next_at=None))
    if not updated.rowcount:
        raise HTTPException(404, "Workflow schedule not found")
    log_action(connection, user, project, "workflow_schedule_stopped", str(schedule_id))
    return {"status": "stopped"}


@app.post("/projects/{project_id}/workflows/{run_id}/cancel")
def cancel_workflow(project_id: UUID, run_id: UUID, user=Depends(authenticate),
                    connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        state = cancel_run(connection, project, str(run_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    log_action(connection, user, project, "workflow_cancelled", str(run_id))
    return {"state": state}


@app.post("/projects/{project_id}/workflows/{run_id}/rerun")
def rerun_workflow(project_id: UUID, run_id: UUID, body: WorkflowRerunInput, user=Depends(authenticate),
                   connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        child = rerun(connection, project, str(run_id), body.failed_node)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    log_action(connection, user, project, "workflow_rerun", child)
    return {"id": child}


@app.get("/projects/{project_id}/workflows/{run_id}/provenance")
def workflow_provenance(project_id: UUID, run_id: UUID, download: bool = False, user=Depends(authenticate),
                         connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    try:
        document = run_provenance.manifest(connection, project, str(run_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{run_id}-provenance.json"'} if download else None
    return JSONResponse(document, headers=headers)


@app.get("/projects/{project_id}/workflows/{run_id}/compare/{other_id}")
def compare_workflow_runs(project_id: UUID, run_id: UUID, other_id: UUID, user=Depends(authenticate),
                          connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    try:
        return run_provenance.compare(connection, project, str(run_id), str(other_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


def can_review_funding(connection, user_id, project):
    try:
        require_project(connection, user_id, project, {"pi", "finance"})
    except PermissionError:
        return False
    return True


@app.get("/projects/{project_id}/notifications")
def notifications_feed(project_id: UUID, after: int = Query(0, ge=0, le=2**63 - 1),
                       limit: int = Query(100, ge=1, le=100),
                       user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    can_review = can_review_funding(connection, user["id"], project)
    items = project_notifications.feed(connection, project, user["id"], after, limit, can_review)
    return {"items": items, "cursor": items[-1]["sequence"] if items else after}


@app.put("/projects/{project_id}/notifications/{notification_id}/read")
def mark_notification(project_id: UUID, notification_id: UUID, body: NotificationReadInput,
                      user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    try:
        return project_notifications.mark(connection, project, user["id"], str(notification_id), body.read,
                                          now_ms(connection), can_review_funding(connection, user["id"], project))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/projects/{project_id}/notifications/announcements")
def announce(project_id: UUID, body: AnnouncementInput, user=Depends(authenticate),
             connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"pi"})
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Announcement message is required")
    enforce_rate_limit("project_announcement", user["id"], 30, API_RATE_WINDOW_MS)
    subject = str(uuid4())
    project_notifications.enqueue(connection, project, "ANNOUNCEMENT", subject, message, now_ms(connection))
    log_action(connection, user, project, "project_announcement", subject)
    return {"id": subject}


@app.get("/projects/{project_id}/funding")
def funding(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    budget = connection.execute(select(budgets).where(budgets.c.project_id == project)).mappings().one()
    query = select(funding_requests).where(funding_requests.c.project_id == project)
    if not user["platform_admin"]:
        role = connection.execute(select(memberships.c.role).where(
            memberships.c.project_id == project, memberships.c.user_id == user["id"],
        )).scalar_one()
        if role == "researcher":
            query = query.where(funding_requests.c.requester == user["id"])
    query = query.order_by(funding_requests.c.id).limit(100)
    return {"budget": dict(budget), "requests": [dict(row) for row in connection.execute(query).mappings()]}


@app.post("/projects/{project_id}/funding")
def submit_funding(project_id: UUID, body: FundingInput,
                   key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
                   user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        request_id = request_funds(connection, project, user["id"], key, body.amount, body.purpose)
        log_action(connection, user, project, "funding_requested", request_id)
        project_notifications.enqueue(connection, project, "APPROVAL_REQUESTED", request_id,
                                      "A funding request needs review", now_ms(connection))
        return {"id": request_id}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/projects/{project_id}/funding/{request_id}/decision")
def review_funding(project_id: UUID, request_id: UUID, body: DecisionInput,
                   user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"finance"})
    try:
        state = decide(connection, project, str(request_id), user["id"], body.approve)
        log_action(connection, user, project, "funding_reviewed", str(request_id))
        project_notifications.enqueue(connection, project, "APPROVAL_DECIDED", str(request_id),
                                      "Funding request " + state.lower(), now_ms(connection))
        return {"state": state}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def storage():
    return LocalStorage(os.environ["RESEARCHHUB_STORAGE"])


async def csv_body(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "text/csv":
        raise HTTPException(415, "Expected text/csv")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD:
            raise HTTPException(413, "CSV exceeds one MiB")
        data.extend(chunk)
    return bytes(data)


@app.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    columns = [column for column in artifacts.c if column.name not in {"payload", "request_key"}]
    query = select(*columns).where(artifacts.c.project_id == project).order_by(artifacts.c.created_at.desc()).limit(100)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.get("/projects/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(project_id: UUID, artifact_id: UUID, user=Depends(authenticate),
                      connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    artifact = connection.execute(select(artifacts).where(
        artifacts.c.project_id == project, artifacts.c.id == str(artifact_id),
    )).mappings().one_or_none()
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    filename = "dataset.csv" if artifact["kind"] == "DATASET" else "result.json"
    return Response(get_bytes(managed_storage(), artifact), media_type=artifact["content_type"], headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@app.get("/projects/{project_id}/datasets")
def list_datasets(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    query = select(datasets).where(datasets.c.project_id == project).order_by(datasets.c.name).limit(100)
    return [dict(row) for row in connection.execute(query).mappings()]


@app.post("/projects/{project_id}/datasets")
def register_dataset(project_id: UUID, body: DatasetInput, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    dataset_id = register(connection, project, user["id"], body.name)
    log_action(connection, user, project, "dataset_registered", dataset_id)
    return {"id": dataset_id}


@app.get("/projects/{project_id}/datasets/{dataset_id}/versions")
def list_versions(project_id: UUID, dataset_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    query = select(versions, artifacts.c.id.label("artifact_id"), artifacts.c.state).join(datasets).outerjoin(
        artifacts, artifacts.c.dataset_version_id == versions.c.id,
    ).where(datasets.c.project_id == project, datasets.c.id == str(dataset_id))
    return [dict(row) for row in connection.execute(query.order_by(versions.c.version.desc()).limit(100)).mappings()]


@app.post("/projects/{project_id}/datasets/{dataset_id}/versions")
def upload_dataset(project_id: UUID, dataset_id: UUID, response: Response,
                   key: str | None = Header(None, alias="Idempotency-Key", min_length=1, max_length=128),
                   user=Depends(authenticate), data=Depends(csv_body)):
    project = str(project_id)
    try:
        with engine.begin() as connection:
            authorize(connection, user, project, COMPUTE_ROLES)
            version, created = stage_upload(connection, project, str(dataset_id), user["id"], data,
                                            now_ms(connection), key)
            if created:
                log_action(connection, user, project, "dataset_uploaded", version["id"])
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (IdempotencyConflict, StorageQuotaExceeded) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if version["state"] == "PENDING":
        with engine.begin() as connection:
            publish_artifact(connection, managed_storage(), now_ms(connection), version["artifact_id"])
            version["state"] = connection.execute(select(artifacts.c.state).where(
                artifacts.c.id == version["artifact_id"],
            )).scalar_one()
    if version["state"] == "PENDING":
        response.status_code = 202
        response.headers["Retry-After"] = "2"
    return version


@app.get("/projects/{project_id}/datasets/{dataset_id}/versions/{version}")
def download_dataset(project_id: UUID, dataset_id: UUID, version: int,
                     user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        data = download(connection, storage(), project, str(dataset_id), version)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if os.getenv("RESEARCHHUB_DEMO_MODE") != "1":
        log_action(connection, user, project, "dataset_downloaded", str(dataset_id))
    return Response(data, media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="dataset.csv"',
        "X-Content-Type-Options": "nosniff",
    })
