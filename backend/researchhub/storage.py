import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol
from uuid import UUID

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
S3_PREFIX = "researchhub/v2/"


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def metadata(self, key: str) -> dict: ...
    def exists(self, key: str) -> bool: ...
    def list_older(self, cutoff_ms: int): ...


def canonical_key(key):
    normalized = str(UUID(key))
    if normalized != key:
        raise ValueError("Artifact key must be a canonical UUID")
    return normalized


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        return self.root / canonical_key(key)

    def put(self, key, data, content_type="application/octet-stream"):
        path = self.path(key)
        with NamedTemporaryFile(dir=self.root, prefix=".staging-", delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temp.unlink(missing_ok=True)
                raise
        try:
            os.link(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def read(self, key):
        with self.path(key).open("rb") as source:
            data = source.read(MAX_ARTIFACT_BYTES + 1)
        if len(data) > MAX_ARTIFACT_BYTES:
            raise OSError("Artifact exceeds supported size")
        return data

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def metadata(self, key):
        stat = self.path(key).stat()
        return {"size": stat.st_size, "modified_ms": stat.st_mtime_ns // 1_000_000}

    def exists(self, key):
        return self.path(key).is_file()

    def list_older(self, cutoff_ms):
        for path in self.root.iterdir():
            try:
                key = canonical_key(path.name)
                if path.is_file() and self.metadata(key)["modified_ms"] < cutoff_ms:
                    yield key
            except (ValueError, FileNotFoundError):
                continue

    def cleanup_staging(self, cutoff_ms):
        for path in self.root.glob(".staging-*"):
            try:
                if path.stat().st_mtime_ns // 1_000_000 < cutoff_ms:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue


class S3Storage:
    def __init__(self, bucket, client):
        self.bucket = bucket
        self.client = client

    def call(self, method, key, **parameters):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(self.client, method)(Bucket=self.bucket, Key=S3_PREFIX + canonical_key(key), **parameters)
        except ClientError as exc:
            status = exc.response["ResponseMetadata"]["HTTPStatusCode"]
            if status == 404:
                raise FileNotFoundError(key) from exc
            if status == 412:
                raise FileExistsError(key) from exc
            raise OSError("Object storage request failed") from exc
        except BotoCoreError as exc:
            raise OSError("Object storage unavailable") from exc

    def put(self, key, data, content_type="application/octet-stream"):
        self.call("put_object", key, Body=data, ContentType=content_type, IfNoneMatch="*",
                  Metadata={"sha256": checksum(data)})

    def read(self, key):
        from botocore.exceptions import BotoCoreError

        result = self.call("get_object", key)
        try:
            with result["Body"] as stream:
                if result["ContentLength"] > MAX_ARTIFACT_BYTES:
                    raise OSError("Artifact exceeds supported size")
                return stream.read(MAX_ARTIFACT_BYTES + 1)
        except BotoCoreError as exc:
            raise OSError("Object storage download failed") from exc

    def delete(self, key):
        self.call("delete_object", key)

    def metadata(self, key):
        result = self.call("head_object", key)
        return {"size": result["ContentLength"], "content_type": result["ContentType"],
                "checksum": result.get("Metadata", {}).get("sha256"),
                "modified_ms": int(result["LastModified"].timestamp() * 1000)}

    def exists(self, key):
        try:
            self.metadata(key)
        except FileNotFoundError:
            return False
        return True

    def list_older(self, cutoff_ms):
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=S3_PREFIX):
            for item in page.get("Contents", []):
                if item["LastModified"].timestamp() * 1000 < cutoff_ms:
                    try:
                        yield canonical_key(item["Key"][len(S3_PREFIX):])
                    except ValueError:
                        continue


def managed_storage(local=None):
    backend = os.getenv("RESEARCHHUB_STORAGE_BACKEND", "local")
    if backend == "local":
        root = local.root if local else Path(os.environ["RESEARCHHUB_STORAGE"])
        return LocalStorage(root / "managed")
    if backend != "s3":
        raise ValueError("Unsupported storage backend")
    return configured_s3()


def configured_s3():
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3", endpoint_url=os.environ["RESEARCHHUB_S3_ENDPOINT"], region_name="us-east-1",
        aws_access_key_id=os.environ["RESEARCHHUB_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RESEARCHHUB_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=3,
                      retries={"total_max_attempts": 1}, s3={"addressing_style": "path"},
                      request_checksum_calculation="when_required", response_checksum_validation="when_required"),
    )
    return S3Storage(os.environ["RESEARCHHUB_S3_BUCKET"], client)


def checksum(data):
    return hashlib.sha256(data).hexdigest()
