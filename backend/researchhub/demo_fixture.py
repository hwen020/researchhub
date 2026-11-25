"""Seed a bounded, shared, read-only synthetic demonstration."""
import os

from sqlalchemy import select

from .auth import hash_password
from .db import connect
from .models import budgets, datasets, memberships, organizations, projects, users, versions, workflow_runs
from .registry import register, upload
from .research_workflows import start_research
from .resource_policy import scheduling_lock
from .storage import LocalStorage, checksum

GUEST_ID = "173ff65d-ed47-4b65-a77d-5a462a2d8e2d"
PROJECT_ID = "a5f1a985-11ed-45ed-b64c-5fa06d01f2e5"
ORG_ID = "859c040a-1e96-4719-acf8-fcbc57988d41"
DATA = b"age,GeneA,GeneB\n20,1,3\n31,2,1\n42,3,5\n53,4,2\n64,5,4\n75,6,6\n"


def demo_project():
    return PROJECT_ID if os.getenv("RESEARCHHUB_DEMO_MODE") == "1" else None


def seed():
    password = os.environ["RESEARCHHUB_DEMO_PASSWORD"]
    storage = LocalStorage(os.environ["RESEARCHHUB_STORAGE"])
    with connect().begin() as connection:
        scheduling_lock(connection)
        existing = connection.execute(select(workflow_runs.c.id).where(
            workflow_runs.c.project_id == PROJECT_ID,
        )).scalar_one_or_none()
        if existing is not None:
            # Render can discard the disk while retaining the PostgreSQL rows.

            restore_dataset(connection, storage)
            return
        connection.execute(organizations.insert().values(id=ORG_ID, name="Synthetic Demonstration"))
        connection.execute(projects.insert().values(
            id=PROJECT_ID, organization_id=ORG_ID, name="Synthetic genomics", max_concurrent=1, max_queued=2,
        ))
        connection.execute(budgets.insert().values(project_id=PROJECT_ID, limit=0))
        connection.execute(users.insert().values(
            id=GUEST_ID, username="demo-guest", password_hash=hash_password(password),
        ))
        connection.execute(memberships.insert().values(project_id=PROJECT_ID, user_id=GUEST_ID, role="researcher"))
        dataset = register(connection, PROJECT_ID, GUEST_ID, "Synthetic ages and expression")
        upload(connection, storage, PROJECT_ID, dataset, DATA)
        start_research(connection, storage, PROJECT_ID, dataset, 1, "genomics")


def restore_dataset(connection, storage):
    row = connection.execute(select(versions).join(datasets).where(
        datasets.c.project_id == PROJECT_ID, versions.c.version == 1,
    )).mappings().one()
    if row["checksum"] != checksum(DATA) or row["size"] != len(DATA):
        raise ValueError("Demo dataset metadata does not match the synthetic fixture")
    try:
        data = storage.read(row["id"])
    except FileNotFoundError:
        storage.put(row["id"], DATA)
    else:
        if data != DATA:
            raise ValueError("Demo dataset content does not match the synthetic fixture")


if __name__ == "__main__":
    seed()
