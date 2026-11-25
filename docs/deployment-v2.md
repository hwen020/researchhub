# ResearchHub deployment modes

## Full local infrastructure

Copy `.env.example` to `.env`, set a random PostgreSQL password, then run:

```sh
docker compose up --build -d --scale worker=2
docker compose exec -e RESEARCHHUB_BOOTSTRAP_USER -e RESEARCHHUB_BOOTSTRAP_PASSWORD api python -m researchhub.bootstrap
```

Export the bootstrap values before invocation. An existing deployment keeps its accounts and uses the Compose schema service to run Alembic. Use a PostgreSQL backup and matching artifact backup before a schema upgrade. The workbench binds to `http://127.0.0.1:8080`. [S3 overlay](artifact-storage.md) and [monitoring profile](observability.md) are optional.

## Public synthetic demonstration

The v2 candidate keeps the existing Render service name and URL. Its Demo profile runs a read-only guest, one allowlisted Genomics pipeline over six synthetic records, and a bounded local Worker. Its fixed result and dataset version are available through authorized downloads. The service checks database readiness at `/api/readyz`. Public credentials are restricted to this mode.

Render Free can suspend an idle web service and discard its local filesystem. Free PostgreSQL expires after 30 days. The Demo does not depend on a separate Worker service or an external S3 bucket. After an authorized replacement of an expired demo database, set its connection value and redeploy the same accepted version. Startup applies migrations and seeds the fixed project and workflow transactionally. On restart with the same database, startup recreates the exact synthetic dataset file if local disk was discarded. [Render Free limits](https://render.com/docs/free).

Before switching an existing service, verify its connected branch, Auto-Deploy and Blueprint Auto-Sync in the authenticated dashboard. The candidate manifest pins the service to main and disables service commit-triggered deploys. Blueprint sync is operated separately by Render. Smoke-test the candidate in isolation, then verify the exact deployed commit, database readiness, blocked legacy accounts and writes, the Genomics DAG, output downloads and the manifest from the public URL. [Render deployments](https://render.com/docs/deploys) and [Blueprint sync](https://render.com/docs/infrastructure-as-code).
