import os

from sqlalchemy import create_engine, event

from .models import metadata


def connect(url=None):
    url = url or os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    return engine


if __name__ == "__main__":
    metadata.create_all(connect())

