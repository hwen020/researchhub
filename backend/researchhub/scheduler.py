import time

from sqlalchemy.exc import OperationalError

from .db import connect
from .workflows import reconcile


def run():
    engine = connect()
    while True:
        try:
            with engine.begin() as connection:
                reconcile(connection)
            time.sleep(0.25)
        except OperationalError:
            time.sleep(1)


if __name__ == "__main__":
    run()

