import csv
import io
from itertools import islice
from uuid import uuid4

from sqlalchemy import func, select

from .artifacts import enqueue, get_bytes, quota_lock
from .models import artifacts, datasets, versions
from .mobility import MAX_ROWS
from .storage import checksum, managed_storage

MAX_UPLOAD = 1024 * 1024


def register(connection, project_id, owner_id, name):
    dataset_id = str(uuid4())
    connection.execute(datasets.insert().values(
        id=dataset_id, project_id=project_id, owner_id=owner_id, name=name,
    ))
    return dataset_id


def validate_csv(data):
    if not 0 < len(data) <= MAX_UPLOAD:
        raise ValueError("CSV must contain at most one MiB")
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
        header = next(reader, [])
        if (not header or not all(header) or len(set(header)) != len(header)
                or "\x00" in data.decode("utf-8-sig")):
            raise ValueError("CSV requires unique column names")
        for row in reader:
            if len(row) != len(header):
                raise ValueError("CSV rows must match the header")
    except (csv.Error, UnicodeDecodeError) as exc:
        raise ValueError("Invalid UTF-8 CSV") from exc

def allocate_version(connection, project_id, dataset_id, data):
    dataset = connection.execute(select(datasets.c.id).where(
        datasets.c.id == dataset_id, datasets.c.project_id == project_id,
    ).with_for_update()).scalar_one_or_none()
    if dataset is None:
        raise LookupError("Dataset not found")
    latest = connection.execute(select(func.max(versions.c.version)).where(
        versions.c.dataset_id == dataset_id,
    )).scalar_one()
    version = dict(id=str(uuid4()), dataset_id=dataset_id, version=(latest or 0) + 1,
                   checksum=checksum(data), size=len(data))
    connection.execute(versions.insert().values(**version))
    return version


def upload(connection, storage, project_id, dataset_id, data):
    validate_csv(data)
    version = allocate_version(connection, project_id, dataset_id, data)
    storage.put(version["id"], data, "text/csv")
    return version


def stage_upload(connection, project_id, dataset_id, owner_id, data, timestamp, key=None):
    validate_csv(data)
    quota_lock(connection, project_id)
    if key is not None:
        existing = connection.execute(select(versions, artifacts.c.id.label("artifact_id"),
                                             artifacts.c.state).join(
            artifacts, artifacts.c.dataset_version_id == versions.c.id,
        ).where(artifacts.c.project_id == project_id, artifacts.c.request_key == key)).mappings().one_or_none()
        if existing is not None:
            if existing["dataset_id"] != dataset_id or existing["checksum"] != checksum(data):
                from .queue import IdempotencyConflict

                raise IdempotencyConflict("Idempotency key already used with a different dataset or content")
            return dict(existing), False
    version = allocate_version(connection, project_id, dataset_id, data)
    artifact_id = enqueue(connection, project_id, data, timestamp, kind="DATASET", content_type="text/csv",
                          version=version["version"], dataset_version_id=version["id"], owner_id=owner_id,
                          request_key=key)
    return dict(version, artifact_id=artifact_id, state="PENDING"), True


def read_version(connection, storage, project_id, dataset_id, version):
    row = connection.execute(select(versions).join(datasets).where(
        datasets.c.project_id == project_id, versions.c.dataset_id == dataset_id,
        versions.c.version == version,
    )).mappings().one_or_none()
    if row is None:
        raise LookupError("Dataset version not found")
    artifact = connection.execute(select(artifacts).where(
        artifacts.c.project_id == project_id, artifacts.c.dataset_version_id == row["id"],
    )).mappings().one_or_none()
    data = get_bytes(managed_storage(storage), artifact) if artifact else storage.read(row["id"])
    if len(data) != row["size"] or checksum(data) != row["checksum"]:
        raise OSError("Dataset integrity check failed")
    return dict(row, artifact_id=artifact["id"] if artifact else None), data


def download(connection, storage, project_id, dataset_id, version):
    return read_version(connection, storage, project_id, dataset_id, version)[1]


def compute_inputs(connection, storage, project_id, dataset_id, version, plugin):
    row, data = read_version(connection, storage, project_id, dataset_id, version)
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if plugin == "summary@1" and fields == ["value"]:
        values = [int(record["value"]) for record in reader]
        parameters = {"observations": values}
    elif plugin == "age-association@1" and "age" in fields and len(fields) > 1:
        expression = {name: [] for name in fields if name != "age"}
        ages = []
        for record in reader:
            ages.append(float(record["age"]))
            for name in expression:
                expression[name].append(float(record[name]))
        parameters = {"ages": ages, "expression": expression}
    elif plugin == "mobility-validate@1":
        parameters = {"rows": list(islice(reader, MAX_ROWS + 1))}
    else:
        raise ValueError("Dataset columns do not match the plugin")
    provenance = {"id": dataset_id, "version": row["version"], "sha256": row["checksum"]}
    if row["artifact_id"] is not None:
        provenance["artifact_id"] = row["artifact_id"]
    return parameters, provenance

