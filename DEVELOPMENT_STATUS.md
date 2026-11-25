# ResearchHub development handoff

## Safe pause and release handoff

Development is paused on `feature/researchhub-v2`. The code and test candidate is `6fd8d765c8647d2ea8215f718b2427c3ecc2ab36`, verified on the remote branch before this documentation-only handoff. [GitHub Actions run 45547622128](https://github.com/hwen020/researchhub/actions/runs/45547622128) was **PENDING** (`in_progress`) when recorded. The handoff commit skips CI and leaves the candidate code and workflows intact.

- Local acceptance recorded 36 passing backend tests using PostgreSQL and VersityGW, and three passing 390 px Edge tests against the isolated two-Worker Compose stack at Alembic head `0012`.
- PostgreSQL stop/start returned HTTP 503 during the outage and 200 after restart. The same idempotency key replayed the retained job, which completed with mean 4. The VersityGW process restart recovered a pending intent and verified the exact staged bytes.
- The complete measurements and methodology are in [benchmarks-v2.md](docs/benchmarks-v2.md). For 1/2/4 Workers, single-project throughput was 1.42/2.50/4.41 jobs/s, and mixed throughput was 1.17/2.33/2.95 jobs/s. Mixed first-half Jain index was 0.960 in all three runs.
- Prometheus configuration parsed successfully. The optional metrics endpoint returned parseable data, and promtool lint flagged missing HELP text. Grafana runtime qualification remains open.
- The existing [v1.0.0 release](https://github.com/hwen020/researchhub/releases/tag/v1.0.0) and [public Demo](https://researchhub-demo.onrender.com) remain in place. The latest public readiness probe returned HTTP 200. Render CLI and an authorized Render API connection were unavailable. The service branch, automatic deploy, Blueprint sync and Free PostgreSQL state require authenticated verification.

### Resume at the release gates

1. Fetch the remote branch and inspect its head and the exact candidate CI run.

   ```sh
   git fetch origin feature/researchhub-v2
   git log -2 --oneline origin/feature/researchhub-v2
   gh run view 45547622128 --repo hwen020/researchhub --json headSha,status,conclusion,jobs
   ```

   If GitHub CLI is unavailable, open the run link above or query the [GitHub REST run endpoint](https://api.github.com/repos/hwen020/researchhub/actions/runs/45547622128). Verify backend, frontend, Compose and the fixed Genomics demo image step for the candidate SHA. Investigate failures before advancing.
2. In the authorized Render dashboard, open the existing ResearchHub Demo service and its Blueprint. Check the connected branch, service auto-deploy, Blueprint auto-sync and the Free database state. Use the [deployment runbook](docs/deployment-v2.md) and [acceptance matrix](docs/v2-acceptance-matrix.md) to close publication gates.
3. After the gates pass, merge the accepted branch to main, verify main CI, publish the v2.0.0 tag and release, and deploy the accepted commit to the existing Render service. Preserve the original v1.0.0 tag and release. Verify readiness, guest restrictions, dataset provenance, all Genomics DAG stages and exports with the following command using the synthetic Demo password supplied through the environment.

   ```sh
   python scripts/check_demo_profile.py https://researchhub-demo.onrender.com
   ```


## v2 development

Independent branch `feature/researchhub-v2` begins at the published v1 documentation commit `b7afbbe`. The current checkpoint covers resource scheduling, advanced workflow lifecycle and two dataset-backed scientific pipelines. The fixed demo profile passed local authorization and genomics execution checks. The live deployment was inspected through readiness only.

The first checkpoint passed 33 PostgreSQL tests and 3 subtests. Later checkpoints added real S3 consistency, persistent notification replay, a local backend contract and measured v2 performance. The latest evidence is recorded in the v2 acceptance matrix. The production frontend bundle built successfully. See [v2 test evidence](docs/test-report-v2.md) and [resume instructions](NEXT_STEPS.md). The headings below record the v1 handoff.

## Release decision

Core v1 development and local acceptance are complete. The independent public repository is `https://github.com/hwen020/researchhub`; GitHub Actions run `45529021806` is green for backend, frontend and compose at license commit `63532a9`. The owner-authorized MIT License and third-party notices are included. Tag `v1.0.0` and GitHub Release are published. The independent Free Demo is live at https://researchhub-demo.onrender.com with documented Free-instance and ephemeral-artifact limitations.

## Verified work

- The handoff base is `4df71f9`; verified local phase commits are `c836a41` (Edge/mobile), `5174185` (administration), `cd0df3c` (rate limits) and `e7119f9` (metrics). The commit author is `ellen-wen <148025129+hwen020@users.noreply.github.com>`.
- Added Alembic `0002` for run manifests, dataset provenance and project audit, then `0003` for persisted worker heartbeats. Upgraded the dedicated PostgreSQL development schema and ran `alembic check`. The development schema had zero application rows at the initial comparison. A separate populated `0001` schema retained its organization, project and queued job through `0003` and passed `alembic check`. The Compose schema job applied the current head from a new database.
- The complete backend suite now passes 25 PostgreSQL integration tests. Coverage includes real PostgreSQL concurrency, process-loss recovery, stale-token fencing, cancellation race, scheduler restart with two independent workers, API restart, database interruption, budget serialization, project isolation, member administration, rate limiting and real metrics. Scientific correctness and repeatability use synthetic inputs.
- Completed a native PostgreSQL 17.12 benchmark with 24 authenticated jobs per case, 4 concurrent submissions and 1, 2 and 4 independently launched workers. Recorded results in [benchmarks](docs/benchmarks.md).
- Fixed the 390px Edge sign-in failure: FastAPI's default HTTP Basic dependency returned `WWW-Authenticate: Basic` for a JSON SPA request, causing Edge fetch to wait on the browser authentication challenge instead of rendering the 401 error. The API now returns challenge-free JSON 401 responses for missing and invalid credentials. The original invalid-credentials assertion remains in the browser test.
- Added migration `0004` for first-login password rotation and system administration audit. Platform admins can create projects in existing organizations and issue one-time random initial passwords; project PIs can manage member roles. Project/system audit records, platform-admin gates, PI escalation denial, self-removal denial, last-PI protection and serialized concurrent PI removals are implemented.
- New accounts cannot access workspace APIs until changing their password. Temporary credential responses are `Cache-Control: no-store`; the UI displays the value once in memory and offers explicit dismissal.
- Added migration `0005` and shared PostgreSQL fixed-window API limits: failed credentials are HMAC-keyed by normalized username (10/5 min) plus a coarser source bucket (60/5 min); job submissions are 120/min, workflows 30/min and dataset uploads 20/min per account. Successful auth and ordinary reads do not consume failed-login quota. The app does not trust forwarded IP headers, counters commit independently of business transactions, return `429`/`Retry-After`, and stale windows are cleaned opportunistically.
- Added migration `0006` with a job-event timestamp index. Admin metrics derive complete queue-wait and per-attempt execution distributions from persisted events over the last 24 hours (bounded to 20,000 events); retry backoff is included in the next queue wait. HTTP request status classes and latency use a per-process ring of the latest 5,000 requests, with no path/user/project labels and `/metrics` excluded from its own samples. The endpoint documents its scope and remains platform-admin-only.
- Fixed API restart routing in `frontend/nginx.conf`: Nginx now resolves the Compose `api` service through Docker DNS at runtime and explicitly strips `/api/` before proxying. Static upstream DNS retained the old API container IP, and dynamic proxy URI rewriting initially mapped requests to `/`; both behaviors were fixed and `nginx -t` passes.
- The complete 390px Edge browser suite passes (2 tests): existing project/job/DAG/dataset/download/funding/audit workflow plus admin project/account creation, member assignment and first-login password rotation. The focused admin browser test also passed after the no-store response change. Frontend TypeScript/production builds pass.
- The dedicated acceptance database upgraded through `0006` and `alembic check` found no model drift. Direct checks passed for admin workflows, concurrent last-PI protection, auth throttling, cross-engine counter sharing, rejected-job no-write behavior, exact synthetic event percentiles, HTTP status aggregation, sample bounding and `/metrics` self-exclusion. The full Edge suite passed after metrics (2 tests), frontend production build passed, and the admin health view displays real metrics.
- Actual dedicated Compose recovery passed: after API container restart a queued job and repeated idempotency key returned the same job; after stopping only `researchhub-acceptance-postgres-1`, readiness returned 503, then recovered after PostgreSQL start, the same queued job/key remained, and the restored two-worker stack completed it. API, frontend, PostgreSQL, scheduler and both workers are running. Added matching automated PostgreSQL integration tests for API restart and unreachable-database 503/recovery.
- Full backend verification is now complete in the isolated Docker API container: pytest/httpx were added temporarily without pip cache, tests ran against the dedicated PostgreSQL service and used random schemas that were cleaned afterward. The host-native limitation is irrelevant to this verification: 25 tests passed in one focused run, with two dependency deprecation warnings before the final run and one Starlette deprecation warning in the final report.

## Resume order

1. Run final source/history/privacy/license audit and establish the independent GitHub repository. After reviewing actual GitHub Actions, publish v1.0.0 only if the release gate passes.
2. Update release documentation and status evidence, run source/history/privacy/license audit, create the independent repository only after that gate, and inspect actual GitHub Actions. Keep v1.0.0 untagged until all required gates pass.
3. Attempt an isolated Render Free demo only if it can preserve truthful persistence, real execution and security. Free web filesystems are ephemeral, free Postgres expires after 30 days, and Free does not provide a background-worker service. [Render Free limits](https://render.com/docs/free).
4. Existing non-v1 follow-up: finalize evidence-backed application materials and the five-minute walkthrough against the accepted v1 build. Published copies show November 26 at 4 p.m. Pacific for requisition #1038135; the official requisition page was not independently verified. [Illinois job portal](https://jobs.illinois.edu/). [Requisition mirror](https://www.highered360.com/jobs/JobDetail.cfm?JobID=179597240).

## Commands and environment

- Native suite from `backend` with the dedicated PostgreSQL endpoint configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`. Run `python -m pytest -q`. The test suite creates and removes its own PostgreSQL schemas.
- Browser setup uses `scripts/seed_browser_fixture.py`, which only seeds an empty database and reads the synthetic password from `RESEARCHHUB_FIXTURE_PASSWORD`. It now seeds a platform-admin fixture as well as PI and finance users. Set the same environment variable when running `npm run test:e2e` from `frontend`. The test base URL defaults to the Compose frontend at port 8080. Windows Edge uses `RESEARCHHUB_BROWSER_CHANNEL=msedge`. The current dedicated acceptance fixture password is the synthetic CI value `synthetic-ci-fixture-only`.
- Docker Desktop's Linux engine responded through the named pipe with approved access. The read-only GitHub API probe also required approved network access. The default sandbox can deny each connection.
- Keep private interpreter paths, local data, environment files and fixture credentials outside tracked files.
