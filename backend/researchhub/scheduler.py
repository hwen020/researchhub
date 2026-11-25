import os
import time

from sqlalchemy.exc import OperationalError

from .artifacts import publish
from .db import connect
from .demo_fixture import demo_project
from .notifications import publish as publish_notifications
from .queue import now_ms
from .storage import managed_storage
from .workflows import reconcile
from .workflow_versions import trigger_due


def run():
    engine = connect()
    project_id = demo_project()
    storage = managed_storage() if project_id is None and os.getenv("RESEARCHHUB_STORAGE") else None
    while True:
        try:
            with engine.begin() as connection:
                if project_id is None:
                    trigger_due(connection)
                reconcile(connection, project_id=project_id)
            if project_id is None:
                with engine.begin() as connection:
                    publish_notifications(connection)
            if storage is not None:
                for _ in range(4):
                    with engine.begin() as connection:
                        if publish(connection, storage, now_ms(connection)) is None:
                            break
            time.sleep(0.25)
        except OperationalError:
            time.sleep(1)


if __name__ == "__main__":
    run()

