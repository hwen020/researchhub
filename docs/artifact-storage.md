# Scientific artifact storage

New dataset versions and fenced job results are tracked as immutable artifacts. The registry displays the project, artifact version, SHA-256 checksum, size, content type and publication state. The API authorizes downloads against the owning project and checks the exact bytes before returning them. Dataset uploads accept CSV up to 1 MiB. Managed result objects are bounded to 2 MiB. Platform administrators can change the storage quota from Resources. Legacy local dataset bytes remain readable through their v1 local adapter.

The default uses the Compose artifact volume. The S3 Compose overlay uses an internal, private VersityGW bucket and an API-authorized download path.

```sh
docker compose -f docker-compose.yml -f docker-compose.s3.yml --profile object-storage up --build -d --scale worker=2
```

Set `RESEARCHHUB_S3_ACCESS_KEY` and `RESEARCHHUB_S3_SECRET_KEY` to distinct local credentials before starting. For a separate compatible server, configure the API and publisher with `RESEARCHHUB_STORAGE_BACKEND=s3`, `RESEARCHHUB_S3_ENDPOINT`, `RESEARCHHUB_S3_BUCKET` and credentials. Use HTTPS for a remote endpoint. Retain the configured backend with its database or migrate objects and verify checksums before switching. The public demo continues to use its fixed synthetic dataset and inline outputs.

MinIO remained the first test choice. Its published image pulls were denied and its official binary download endpoint returned HTTP 410. [VersityGW POSIX backend](https://github.com/versity/versitygw/wiki/POSIX-Backend) supports S3 conditional writes without a cloud account.
