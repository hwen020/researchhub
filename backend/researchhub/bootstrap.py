import os
from uuid import uuid4

from sqlalchemy import select

from .auth import hash_password
from .db import connect
from .models import budgets, memberships, organizations, projects, users


def main():
    username = os.environ["RESEARCHHUB_BOOTSTRAP_USER"]
    password_hash = hash_password(os.environ["RESEARCHHUB_BOOTSTRAP_PASSWORD"])
    with connect().begin() as conn:
        if conn.execute(select(users.c.id).limit(1)).first():
            raise SystemExit("Bootstrap requires an empty user table")
        user, organization, project = [str(uuid4()) for _ in range(3)]
        conn.execute(users.insert().values(
            id=user, username=username, password_hash=password_hash, platform_admin=1,
        ))
        conn.execute(organizations.insert().values(id=organization, name="Synthetic Research Lab"))
        conn.execute(projects.insert().values(id=project, organization_id=organization, name="Sample Statistics"))
        conn.execute(budgets.insert().values(project_id=project, limit=100_000))
        conn.execute(memberships.insert().values(project_id=project, user_id=user, role="pi"))
        print(project)


if __name__ == "__main__":
    main()

