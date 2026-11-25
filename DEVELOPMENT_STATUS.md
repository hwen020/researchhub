# ResearchHub development handoff

## Release decision

v1.0 requires another development and acceptance pass. No official tag, release, public demo or v2 branch has been created.

## Verified work

- The handoff base is `4df71f9`; verified local phase commits are `c836a41` (Edge/mobile) and `5174185` (administration). The commit author is `ellen-wen <148025129+hwen020@users.noreply.github.com>`.
- Added Alembic `0002` for run manifests, dataset provenance and project audit, then `0003` for persisted worker heartbeats. Upgraded the dedicated PostgreSQL development schema and ran `alembic check`. The development schema had zero application rows at the initial comparison. A separate populated `0001` schema retained its organization, project and queued job through `0003` and passed `alembic check`. The Compose schema job applied the current head from a new database.
- The latest native backend run passed 18 tests with two dependency deprecation warnings. Coverage includes real PostgreSQL concurrency, process-loss recovery, stale-token fencing, cancellation race, scheduler restart with two independent workers, budget consistency and HTTP project isolation. A TestClient exercised project-scoped dataset, audit and manifest routes. Scientific correctness and repeatability use synthetic inputs.
- Completed a native PostgreSQL 17.12 benchmark with 24 authenticated jobs per case, 4 concurrent submissions and 1, 2 and 4 independently launched workers. Recorded results in [benchmarks](docs/benchmarks.md).
- Fixed the 390px Edge sign-in failure: FastAPI's default HTTP Basic dependency returned `WWW-Authenticate: Basic` for a JSON SPA request, causing Edge fetch to wait on the browser authentication challenge instead of rendering the 401 error. The API now returns challenge-free JSON 401 responses for missing and invalid credentials. The original invalid-credentials assertion remains in the browser test.
- Added migration `0004` for first-login password rotation and system administration audit. Platform admins can create projects in existing organizations and issue one-time random initial passwords; project PIs can manage member roles. Project/system audit records, platform-admin gates, PI escalation denial, self-removal denial, last-PI protection and serialized concurrent PI removals are implemented.
- New accounts cannot access workspace APIs until changing their password. Temporary credential responses are `Cache-Control: no-store`; the UI displays the value once in memory and offers explicit dismissal.
- Added migration `0005` and shared PostgreSQL fixed-window API limits: failed credentials are HMAC-keyed by normalized username (10/5 min) plus a coarser source bucket (60/5 min); job submissions are 120/min, workflows 30/min and dataset uploads 20/min per account. Successful auth and ordinary reads do not consume failed-login quota. The app does not trust forwarded IP headers, counters commit independently of business transactions, return `429`/`Retry-After`, and stale windows are cleaned opportunistically.
- The complete 390px Edge browser suite passes (2 tests): existing project/job/DAG/dataset/download/funding/audit workflow plus admin project/account creation, member assignment and first-login password rotation. The focused admin browser test also passed after the no-store response change. Frontend TypeScript/production builds pass.
- The dedicated acceptance database upgraded through `0005` and `alembic check` found no model drift. Direct API checks passed for admin workflows, concurrent last-PI protection, auth throttling, cross-engine counter sharing and job rejection without a queue write. The full Edge suite remains 2/2 after the limiter change. Four PostgreSQL integration regressions have been added since the baseline, but cannot run natively here: host Python is 3.8 without pytest/FastAPI, the container lacks pytest/httpx, and no native test database URL is configured. The last fully reported native baseline remains 18 passing tests.

## Resume order

1. Expose persisted queue-wait/execution metrics and bounded HTTP request metrics. Keep administrative metrics protected.
2. Add API restart and PostgreSQL interruption/recovery tests using only the dedicated `researchhub-acceptance` environment; then run the full backend, frontend, Edge/Chromium browser and multi-worker Compose suite.
3. Update release documentation and status evidence, run source/history/privacy/license audit, create the independent repository only after that gate, and inspect actual GitHub Actions. Keep v1.0.0 untagged until all required gates pass.
4. Attempt an isolated Render Free demo only if it can preserve truthful persistence, real execution and security. Free web filesystems are ephemeral, free Postgres expires after 30 days, and Free does not provide a background-worker service. [Render Free limits](https://render.com/docs/free).
5. Existing non-v1 follow-up: finalize evidence-backed application materials and the five-minute walkthrough against the accepted v1 build. Published copies show November 26 at 4 p.m. Pacific for requisition #1038135; the official requisition page was not independently verified. [Illinois job portal](https://jobs.illinois.edu/). [Requisition mirror](https://www.highered360.com/jobs/JobDetail.cfm?JobID=179597240).

## Commands and environment

- Native suite from `backend` with the dedicated PostgreSQL endpoint configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`. Run `python -m pytest -q`. The test suite creates and removes its own PostgreSQL schemas.
- Browser setup uses `scripts/seed_browser_fixture.py`, which only seeds an empty database and reads the synthetic password from `RESEARCHHUB_FIXTURE_PASSWORD`. It now seeds a platform-admin fixture as well as PI and finance users. Set the same environment variable when running `npm run test:e2e` from `frontend`. The test base URL defaults to the Compose frontend at port 8080. Windows Edge uses `RESEARCHHUB_BROWSER_CHANNEL=msedge`. The current dedicated acceptance fixture password is the synthetic CI value `synthetic-ci-fixture-only`.
- Docker Desktop's Linux engine responded through the named pipe with approved access. The read-only GitHub API probe also required approved network access. The default sandbox can deny each connection.
- Keep private interpreter paths, local data, environment files and fixture credentials outside tracked files.
