"""Durable artifact intents and an idempotent object publisher."""
import argparse
from time import perf_counter, sleep
from uuid import uuid4

from sqlalchemy import func, select, text

from .models import artifacts, datasets, projects, versions
from .observability import correlation_id, emit
from .storage import MAX_ARTIFACT_BYTES, checksum, managed_storage


class ArtifactUnavailable(OSError):
    pass


class StorageQuotaExceeded(ValueError):
    pass


class ArtifactIntegrityError(ArtifactUnavailable):
    pass


def quota_lock(connection, project_id):
    if connection.dialect.name == "postgresql":
        connection.execute(text(
            "SELECT pg_advisory_xact_lock(hashtext(current_schema()) # 718411375, hashtext(:project_id))"
        ), {"project_id": project_id})


def usage(connection, project_id):
    stored = connection.execute(select(func.coalesce(func.sum(artifacts.c.size), 0)).where(
        artifacts.c.project_id == project_id,
    )).scalar_one()
    legacy = connection.execute(select(func.coalesce(func.sum(versions.c.size), 0)).select_from(
        versions.join(datasets).outerjoin(artifacts, artifacts.c.dataset_version_id == versions.c.id)
    ).where(datasets.c.project_id == project_id, artifacts.c.id.is_(None))).scalar_one()
    return int(stored + legacy)


def enqueue(connection, project_id, data, timestamp, *, kind, content_type, version=1,
            dataset_version_id=None, job_id=None, owner_id=None, request_key=None, trace_id=None):
    if not 0 < len(data) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact size must be between one byte and two MiB")
    quota_lock(connection, project_id)
    limit = connection.execute(select(projects.c.storage_quota_bytes).where(
        projects.c.id == project_id,
    )).scalar_one()
    already_counted = len(data) if dataset_version_id else 0
    if usage(connection, project_id) + len(data) - already_counted > limit:
        raise StorageQuotaExceeded("Project storage quota exhausted")
    artifact_id = str(uuid4())
    connection.execute(artifacts.insert().values(
        id=artifact_id, project_id=project_id, owner_id=owner_id,
        dataset_version_id=dataset_version_id, job_id=job_id, request_key=request_key,
        kind=kind, version=version, checksum=checksum(data), size=len(data),
        content_type=content_type, state="PENDING", payload=data, attempts=0,
        created_at=timestamp, next_attempt_at=timestamp, correlation_id=correlation_id(trace_id),
    ))
    return artifact_id


def verified(storage, artifact):
    try:
        data = storage.read(artifact["id"])
    except OSError as exc:
        raise ArtifactUnavailable("Artifact object is unavailable") from exc
    if len(data) != artifact["size"] or checksum(data) != artifact["checksum"]:
        raise ArtifactIntegrityError("Artifact checksum mismatch")
    return data


def publish(connection, storage, timestamp, artifact_id=None):
    query = select(artifacts).where(artifacts.c.state == "PENDING", artifacts.c.next_attempt_at <= timestamp)
    if artifact_id is not None:
        query = query.where(artifacts.c.id == artifact_id)
    row = connection.execute(query.order_by(artifacts.c.next_attempt_at, artifacts.c.id)
                             .limit(1).with_for_update(skip_locked=True)).mappings().one_or_none()
    if row is None:
        return None
    started = perf_counter()
    attempts = row["attempts"] + 1
    try:
        try:
            storage.put(row["id"], row["payload"], row["content_type"])
        except FileExistsError:
            pass
        verified(storage, row)
    except ArtifactIntegrityError:
        values = {"state": "FAILED", "last_error": "checksum_mismatch", "payload": None}
    except OSError:
        values = {"last_error": "object_unavailable",
                  "next_attempt_at": timestamp + min(60_000, 500 * 2 ** min(attempts, 7))}
    else:
        values = {"state": "AVAILABLE", "payload": None, "last_error": None,
                  "publish_ms": int((perf_counter() - started) * 1000)}
    connection.execute(artifacts.update().where(artifacts.c.id == row["id"]).values(
        attempts=attempts, **values,
    ))
    state = values.get("state", "PENDING")
    emit("artifact_publication_attempt", correlation_id=row["correlation_id"], artifact_id=row["id"],
         job_id=row["job_id"], attempt=attempts, provisional_state=state)
    return state


def get_bytes(storage, artifact):
    if artifact["state"] != "AVAILABLE":
        raise ArtifactUnavailable("Artifact publication is " + artifact["state"].lower())
    return verified(storage, artifact)


def cleanup_orphans(connection, storage, cutoff_ms):
    removed = 0
    for key in storage.list_older(cutoff_ms):
        exists = connection.execute(select(artifacts.c.id).where(artifacts.c.id == key)).first()
        if not exists:
            storage.delete(key)
            removed += 1
    if hasattr(storage, "cleanup_staging"):
        storage.cleanup_staging(cutoff_ms)
    return removed


def initialize_bucket(storage):
    from botocore.exceptions import BotoCoreError, ClientError

    for attempt in range(15):
        try:
            storage.client.head_bucket(Bucket=storage.bucket)
            return
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                storage.client.create_bucket(Bucket=storage.bucket)
                return
            raise
        except BotoCoreError:
            if attempt == 14:
                raise
            sleep(1)


def main():
    from .db import connect
    from .queue import now_ms

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("cleanup-orphans", "init-bucket"))
    args = parser.parse_args()
    storage = managed_storage()
    if args.action == "init-bucket":
        initialize_bucket(storage)
        return
    with connect().begin() as connection:
        removed = cleanup_orphans(connection, storage, now_ms(connection) - 86_400_000)
    print(f"Removed {removed} unreferenced objects")


if __name__ == "__main__":
    main()
