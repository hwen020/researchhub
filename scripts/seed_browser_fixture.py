"""Seed an empty acceptance database with synthetic projects and scoped accounts."""

import os
from uuid import uuid4

from sqlalchemy import select

from researchhub.auth import hash_password
from researchhub.db import connect
from researchhub.models import budgets, memberships, organizations, projects, users
from researchhub.registry import register, upload
from researchhub.storage import LocalStorage


def seed():
    secret = os.environ["RESEARCHHUB_FIXTURE_PASSWORD"]
    with connect().begin() as conn:
        if conn.execute(select(users.c.id).limit(1)).first():
            raise SystemExit("Browser fixtures require an empty synthetic test database")
        organization, primary, secondary, pi, finance, admin = (str(uuid4()) for _ in range(6))
        conn.execute(organizations.insert().values(id=organization, name="Fixture Lab"))
        for project, name in ((primary, "Primary fixture"), (secondary, "Secondary fixture")):
            conn.execute(projects.insert().values(id=project, organization_id=organization, name=name))
            conn.execute(budgets.insert().values(project_id=project, limit=5000))
        for user, label, platform_admin in ((pi, "pi", 0), (finance, "finance", 0), (admin, "admin", 1)):
            conn.execute(users.insert().values(
                id=user, username="fixture-" + label, password_hash=hash_password(secret),
                platform_admin=platform_admin,
            ))
        conn.execute(memberships.insert(), [
            {"project_id": primary, "user_id": pi, "role": "pi"},
            {"project_id": secondary, "user_id": pi, "role": "researcher"},
            {"project_id": primary, "user_id": finance, "role": "finance"},
        ])
        dataset = register(conn, primary, pi, "Synthetic fixture")
        upload(conn, LocalStorage(os.environ["RESEARCHHUB_STORAGE"]), primary, dataset, b"value\n1\n2\n3\n")


if __name__ == "__main__":
    seed()
