# ResearchHub development handoff

## Release decision

v1.0 requires another development and acceptance pass. No official tag, release, public demo or v2 branch has been created.

## Verified work

- The active development checkpoint is `4df71f9`. The commit author is `ellen-wen <148025129+hwen020@users.noreply.github.com>`.
- Added Alembic `0002` for run manifests, dataset provenance and project audit, then `0003` for persisted worker heartbeats. Upgraded the dedicated PostgreSQL development schema and ran `alembic check`. The development schema had zero application rows at the initial comparison. A separate populated `0001` schema retained its organization, project and queued job through `0003` and passed `alembic check`. The Compose schema job applied the current head from a new database.
- The latest native backend run passed 18 tests with two dependency deprecation warnings. Coverage includes real PostgreSQL concurrency, process-loss recovery, stale-token fencing, cancellation race, scheduler restart with two independent workers, budget consistency and HTTP project isolation. A TestClient exercised project-scoped dataset, audit and manifest routes. Scientific correctness and repeatability use synthetic inputs.
- Completed a native PostgreSQL 17.12 benchmark with 24 authenticated jobs per case, 4 concurrent submissions and 1, 2 and 4 independently launched workers. Recorded results in [benchmarks](docs/benchmarks.md).
- Fixed the 390px Edge sign-in failure: FastAPI's default HTTP Basic dependency returned `WWW-Authenticate: Basic` for a JSON SPA request, causing Edge fetch to wait on the browser authentication challenge instead of rendering the 401 error. The API now returns challenge-free JSON 401 responses for missing and invalid credentials. The original invalid-credentials assertion remains in the browser test.
- The full 390px Edge browser flow now passes (1 test), covering project isolation, dataset views, job/DAG execution, artifact download, funding approval, audit, readiness and the 390px overflow assertion. This run also exposed and fixed a grid min-content overflow caused by long audit JSON.
- The frontend TypeScript/production build passes. A PostgreSQL integration regression for missing/invalid Basic credentials was added; it could not be run natively in this environment because the host Python is 3.8 without pytest/FastAPI and no native test database URL is configured. Equivalent missing/invalid credential responses were verified through the isolated Compose API proxy.

## Resume order

1. Implement compact project, membership and account administration with project-scoped permissions, audit records, one-time synthetic-safe initial password delivery and forced first-login rotation. Add backend and browser coverage.
2. Add shared PostgreSQL-backed API rate limits, then expose persisted queue-wait/execution metrics and bounded HTTP request metrics. Keep administrative metrics protected.
3. Add API restart and PostgreSQL interruption/recovery tests using only the dedicated `researchhub-acceptance` environment; then run the full backend, frontend, Edge/Chromium browser and multi-worker Compose suite.
4. Update release documentation and status evidence, run source/history/privacy/license audit, create the independent repository only after that gate, and inspect actual GitHub Actions. Keep v1.0.0 untagged until all required gates pass.
5. Attempt an isolated Render Free demo only if it can preserve truthful persistence, real execution and security. Free web filesystems are ephemeral, free Postgres expires after 30 days, and Free does not provide a background-worker service. [Render Free limits](https://render.com/docs/free).
5. Finalize evidence-backed application materials and the five-minute walkthrough against the accepted v1 build. Published copies show November 26 at 4 p.m. Pacific for requisition #1038135. The official requisition page was not independently verified. [Illinois job portal](https://jobs.illinois.edu/). [Requisition mirror](https://www.highered360.com/jobs/JobDetail.cfm?JobID=179597240).

## Commands and environment

- Native suite from `backend` with the dedicated PostgreSQL endpoint configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`. Run `python -m pytest -q`. The test suite creates and removes its own PostgreSQL schemas.
- Browser setup uses `scripts/seed_browser_fixture.py`, which only seeds an empty database and reads the synthetic password from `RESEARCHHUB_FIXTURE_PASSWORD`. Set the same environment variable when running `npm run test:e2e` from `frontend`. The test base URL defaults to the Compose frontend at port 8080. Windows Edge uses `RESEARCHHUB_BROWSER_CHANNEL=msedge`. The current dedicated acceptance fixture password is the synthetic CI value `synthetic-ci-fixture-only`.
- Docker Desktop's Linux engine responded through the named pipe with approved access. The read-only GitHub API probe also required approved network access. The default sandbox can deny each connection.
- Keep private interpreter paths, local data, environment files and fixture credentials outside tracked files.
