import time

from sqlalchemy.exc import OperationalError

from .db import connect
from .demo_fixture import demo_project
from .workflows import reconcile
from .workflow_versions import trigger_due


def run():
    engine = connect()
    project_id = demo_project()
    while True:
        try:
            with engine.begin() as connection:
                if project_id is None:
                    trigger_due(connection)
                reconcile(connection, project_id=project_id)
            time.sleep(0.25)
        except OperationalError:
            time.sleep(1)


if __name__ == "__main__":
    run()

