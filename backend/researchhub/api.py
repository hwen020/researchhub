import csv
import io
import os
import secrets
from typing import Dict, List, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from .auth import hash_password, require_project, verify_password
from .db import connect
from .finance import decide, request_funds
from .models import audit, budgets, datasets, events, funding_requests, jobs, memberships, organizations, projects, system_audit, users, versions, workers, workflow_runs
from .plugins import validate_parameters
from .queue import IdempotencyConflict, cancel, now_ms, submit
from .registry import MAX_UPLOAD, compute_inputs, download, register, upload
from .storage import LocalStorage
from .workflows import start

app = FastAPI(title="ResearchHub")
engine = connect()
security = HTTPBasic(auto_error=False)
dummy_hash = hash_password(uuid4().hex)
ALL_ROLES = {"pi", "researcher", "finance"}
COMPUTE_ROLES = {"pi", "researcher"}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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


class NodeInput(RequestModel):
    plugin: Literal["summary@1", "age-association@1"]
    parameters: dict
    depends_on: List[str] = Field(default_factory=list, max_length=64)


class WorkflowInput(RequestModel):
    nodes: Dict[str, NodeInput] = Field(min_length=1, max_length=64)


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


def authenticate(request: Request, credentials: HTTPBasicCredentials | None = Depends(security), connection=Depends(transaction, scope="function")):
    user = None
    password = "missing credential"
    if credentials is not None:
        user = connection.execute(select(users).where(users.c.username == credentials.username[:101])).mappings().one_or_none()
        password = credentials.password
    if not verify_password(password, user["password_hash"] if user else dummy_hash) or user is None:
        raise HTTPException(401, "Invalid credentials")
    if user["must_change_password"] and request.url.path not in {"/auth/status", "/auth/password"}:
        raise HTTPException(403, "Password change required")
    return user


def authorize(connection, user, project_id, roles):
    if connection.execute(select(projects.c.id).where(projects.c.id == project_id)).scalar_one_or_none() is None:
        raise HTTPException(404, "Project not found")
    try:
        require_project(connection, user["id"], project_id, roles)
    except PermissionError as exc:
        raise HTTPException(404, "Project not found") from exc


def public_job(job):
    return {key: job[key] for key in ("id", "state", "plugin", "attempt", "created_at", "result")}


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
            "must_change_password": bool(user["must_change_password"])}


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
def download_job(project_id: UUID, job_id: UUID, kind: Literal["manifest", "json", "csv"],
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
    log_action(connection, user, project, "job_artifact_download", str(job_id))
    if kind != "csv":
        return JSONResponse(row["manifest"] if kind == "manifest" else row["result"], headers=headers)
    records = row["result"].get("associations", [row["result"]])
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
    return {"jobs_by_state": states, "workers_online": active, "retries": retries,
            "queue_depth": states.get("QUEUED", 0) + states.get("RETRYING", 0)}


@app.get("/projects")
def list_projects(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    query = select(projects.c.id, projects.c.name, organizations.c.name.label("organization")).join(organizations)
    if not user["platform_admin"]:
        query = query.join(memberships, memberships.c.project_id == projects.c.id).where(
            memberships.c.user_id == user["id"],
        ).add_columns(memberships.c.role)
    else:
        query = query.add_columns(literal("platform_admin").label("role"))
    return [dict(row) for row in connection.execute(query.order_by(projects.c.name, projects.c.id)).mappings()]


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
                     max_attempts=body.max_attempts, timeout_ms=body.timeout_ms, provenance=provenance)
    except LookupError as exc:
        raise HTTPException(404, "Dataset version not found") from exc
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "job_submission", job["id"])
    return public_job(job)


@app.get("/projects/{project_id}/jobs")
def project_jobs(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(jobs).where(jobs.c.project_id == project).order_by(jobs.c.created_at.desc(), jobs.c.id).limit(100)
    return [public_job(row) for row in connection.execute(query).mappings()]


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
        definition = body.model_dump()["nodes"]
        for node in definition.values():
            node["parameters"] = validate_parameters(node["plugin"], node["parameters"])
        run_id = start(connection, project, definition)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_action(connection, user, project, "workflow_started", run_id)
    return {"id": run_id}


@app.get("/projects/{project_id}/workflows")
def list_workflows(project_id: UUID, user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, ALL_ROLES)
    query = select(workflow_runs.c.id, workflow_runs.c.state, workflow_runs.c.nodes).where(
        workflow_runs.c.project_id == project,
    ).order_by(workflow_runs.c.checked_at.desc(), workflow_runs.c.id).limit(100)
    return [dict(row) for row in connection.execute(query).mappings()]


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
    query = select(versions).join(datasets).where(datasets.c.project_id == project, datasets.c.id == str(dataset_id))
    return [dict(row) for row in connection.execute(query.order_by(versions.c.version.desc()).limit(100)).mappings()]


@app.post("/projects/{project_id}/datasets/{dataset_id}/versions")
def upload_dataset(project_id: UUID, dataset_id: UUID, user=Depends(authenticate), data=Depends(csv_body),
                   connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        version = upload(connection, storage(), project, str(dataset_id), data)
        log_action(connection, user, project, "dataset_uploaded", version["id"])
        return version
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/projects/{project_id}/datasets/{dataset_id}/versions/{version}")
def download_dataset(project_id: UUID, dataset_id: UUID, version: int,
                     user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        data = download(connection, storage(), project, str(dataset_id), version)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    log_action(connection, user, project, "dataset_downloaded", str(dataset_id))
    return Response(data, media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="dataset.csv"',
        "X-Content-Type-Options": "nosniff",
    })
