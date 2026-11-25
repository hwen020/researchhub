"""Inject a real VersityGW process outage against a disposable PostgreSQL schema."""
import argparse
import os
from pathlib import Path
from secrets import token_hex
import socket
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from researchhub.artifacts import get_bytes, initialize_bucket, publish
from researchhub.db import connect
from researchhub.models import artifacts, metadata, organizations, projects, users
from researchhub.queue import now_ms
from researchhub.registry import register, stage_upload
from researchhub.storage import configured_s3

DATA = b"value\n1\n2\n"


def run(binary):
    url = os.environ["RESEARCHHUB_TEST_DATABASE"]
    base = connect(url)
    schema = "rh_s3_restart_" + uuid4().hex
    with base.begin() as connection:
        connection.execute(text("CREATE SCHEMA " + schema))
    engine = connect(make_url(url).update_query_dict({"options": "-csearch_path=" + schema}))
    access, secret = token_hex(12), token_hex(24)
    worker_environment = {**os.environ, "ROOT_ACCESS_KEY": access, "ROOT_SECRET_KEY": secret}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    os.environ.update(
        RESEARCHHUB_S3_ENDPOINT=f"http://127.0.0.1:{port}",
        RESEARCHHUB_S3_BUCKET="researchhub-recovery", RESEARCHHUB_S3_ACCESS_KEY=access,
        RESEARCHHUB_S3_SECRET_KEY=secret,
    )

    def start_store(root):
        return subprocess.Popen([binary, "--port", f"127.0.0.1:{port}", "posix", root],
                                env=worker_environment, stdout=subprocess.DEVNULL)

    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(organizations.insert().values(id="org", name="Synthetic"))
            connection.execute(projects.insert().values(id="project", organization_id="org", name="Recovery"))
            connection.execute(users.insert().values(id="tester", username="synthetic", password_hash="fixture"))
            dataset = register(connection, "project", "tester", "Synthetic table")
            version, _ = stage_upload(connection, "project", dataset, "tester", DATA, now_ms(connection), "outage")
            artifact_id = version["artifact_id"]

        with TemporaryDirectory(prefix="rh-object-fault-") as directory:
            root = str(Path(directory) / "objects")
            Path(root).mkdir()
            store = start_store(root)
            try:
                initialize_bucket(configured_s3())
                store.kill()
                store.wait(timeout=10)
                with engine.begin() as connection:
                    assert publish(connection, configured_s3(), now_ms(connection), artifact_id) == "PENDING"
                store = start_store(root)
                storage = configured_s3()
                initialize_bucket(storage)
                with engine.begin() as connection:
                    assert publish(connection, storage, now_ms(connection) + 2000, artifact_id) == "AVAILABLE"
                    record = connection.execute(select(artifacts).where(artifacts.c.id == artifact_id)).mappings().one()
                    assert get_bytes(storage, record) == DATA
            finally:
                if store.poll() is None:
                    store.kill()
                    store.wait(timeout=10)
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        base.dispose()
    print("S3 process loss, durable pending intent and checksum-verified publication after restart passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("versitygw_binary")
    run(parser.parse_args().versitygw_binary)
