import csv
import io
from uuid import uuid4

from sqlalchemy import func, select

from .models import datasets, versions
from .storage import checksum

MAX_UPLOAD = 1024 * 1024


def register(connection, project_id, owner_id, name):
    dataset_id = str(uuid4())
    connection.execute(datasets.insert().values(
        id=dataset_id, project_id=project_id, owner_id=owner_id, name=name,
    ))
    return dataset_id


def upload(connection, storage, project_id, dataset_id, data):
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
    storage.put(version["id"], data)
    return version


def download(connection, storage, project_id, dataset_id, version):
    row = connection.execute(select(versions).join(datasets).where(
        datasets.c.project_id == project_id, versions.c.dataset_id == dataset_id,
        versions.c.version == version,
    )).mappings().one_or_none()
    if row is None:
        raise LookupError("Dataset version not found")
    data = storage.read(row["id"])
    if len(data) != row["size"] or checksum(data) != row["checksum"]:
        raise OSError("Dataset integrity check failed")
    return data

