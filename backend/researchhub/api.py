import os
from typing import Dict, List, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .auth import hash_password, require_project, verify_password
from .db import connect
from .finance import decide, request_funds
from .models import budgets, datasets, events, funding_requests, jobs, memberships, organizations, projects, users, versions, workflow_runs
from .plugins import validate_parameters
from .queue import IdempotencyConflict, cancel, submit
from .registry import MAX_UPLOAD, download, register, upload
from .storage import LocalStorage
from .workflows import start

app = FastAPI(title="ResearchHub")
engine = connect()
security = HTTPBasic()
dummy_hash = hash_password(uuid4().hex)
ALL_ROLES = {"pi", "researcher", "finance"}
COMPUTE_ROLES = {"pi", "researcher"}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class JobInput(RequestModel):
    plugin: Literal["summary@1", "age-association@1"]
    parameters: dict
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


def transaction():
    try:
        with engine.begin() as connection:
            yield connection
    except OperationalError as exc:
        raise HTTPException(503, "Database unavailable") from exc


def authenticate(credentials: HTTPBasicCredentials = Depends(security), connection=Depends(transaction, scope="function")):
    user = connection.execute(select(users).where(users.c.username == credentials.username[:101])).mappings().one_or_none()
    if not verify_password(credentials.password, user["password_hash"] if user else dummy_hash) or user is None:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})
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


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready(connection=Depends(transaction, scope="function")):
    connection.execute(select(jobs.c.id).limit(1))
    return {"status": "ready"}


@app.get("/metrics")
def metrics(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    if not user["platform_admin"]:
        raise HTTPException(403, "Platform administrator required")
    counts = connection.execute(select(jobs.c.state, func.count()).group_by(jobs.c.state))
    return {"jobs_by_state": dict(counts.all())}


@app.get("/projects")
def list_projects(user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    query = select(projects.c.id, projects.c.name, organizations.c.name.label("organization")).join(organizations)
    if not user["platform_admin"]:
        query = query.join(memberships, memberships.c.project_id == projects.c.id).where(memberships.c.user_id == user["id"])
    return [dict(row) for row in connection.execute(query.order_by(projects.c.name, projects.c.id)).mappings()]


@app.post("/projects/{project_id}/jobs")
def submit_job(project_id: UUID, body: JobInput,
               key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
               user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    if key.startswith("dag:"):
        raise HTTPException(422, "Reserved idempotency prefix")
    try:
        parameters = validate_parameters(body.plugin, body.parameters)
        job = submit(connection, project, key, body.plugin, parameters,
                     max_attempts=body.max_attempts, timeout_ms=body.timeout_ms)
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    authorize(connection, user, project, {"pi", "finance"})
    budget = connection.execute(select(budgets).where(budgets.c.project_id == project)).mappings().one()
    query = select(funding_requests).where(funding_requests.c.project_id == project).limit(100)
    return {"budget": dict(budget), "requests": [dict(row) for row in connection.execute(query).mappings()]}


@app.post("/projects/{project_id}/funding")
def submit_funding(project_id: UUID, body: FundingInput,
                   key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
                   user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, COMPUTE_ROLES)
    try:
        return {"id": request_funds(connection, project, user["id"], key, body.amount, body.purpose)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/projects/{project_id}/funding/{request_id}/decision")
def review_funding(project_id: UUID, request_id: UUID, body: DecisionInput,
                   user=Depends(authenticate), connection=Depends(transaction, scope="function")):
    project = str(project_id)
    authorize(connection, user, project, {"finance"})
    try:
        return {"state": decide(connection, project, str(request_id), user["id"], body.approve)}
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
    return {"id": register(connection, project, user["id"], body.name)}


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
        return upload(connection, storage(), project, str(dataset_id), data)
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
    return Response(data, media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="dataset.csv"',
        "X-Content-Type-Options": "nosniff",
    })

