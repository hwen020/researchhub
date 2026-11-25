# Progress

- Isolated v2 work on `feature/researchhub-v2`. Baseline GitHub Actions run `45531997808` passed, and the public readiness endpoint returned HTTP 200.
- Added migration 0007, transactional resource admission, persisted project rotation, aging, worker capability matching and queue saturation reporting.
- Added migration 0008, immutable workflow templates, conditional dependencies, lineage, local reruns and persistent schedules.
- Exercised the fixed Genomics demo and Wearable Mobility exports with independent scheduler and worker processes. The local test checkpoint passed 33 tests and 3 subtests.
- Pushed the Phase 0-3 checkpoint. GitHub Actions run 45544377608 passed. Both 390 px Edge tests passed against isolated two-worker Compose.
- Added immutable artifact intents, storage quotas and retryable publication. The default storage snapshot passed 34 tests, and the S3-only test passed separately against VersityGW v1.7.0.

- Resumed from handoff checkpoint `4df71f9`; committed Edge/mobile fixes as `c836a41`, administration as `5174185`, rate limits as `cd0df3c`, metrics as `e7119f9`, recovery as `dd0df55`, and full-regression fixes as `0286174`.
- Added incremental migrations for run manifests, audit and worker heartbeats.
- Native PostgreSQL tests exercise concurrent claims, stale results, worker process loss, funding consistency, API isolation and dataset provenance.
- Recorded native 1/2/4-worker runs using real authenticated HTTP submissions.
- Added a Compose browser fixture and a GitHub Actions workflow.
- Fixed the Edge Basic-auth challenge that blocked SPA login errors and resolved a 390px audit-content overflow. The full mobile Edge browser flow passes (1 test); frontend production build passes. Added a PostgreSQL auth-response regression test, with direct API response behavior verified through the isolated Compose stack.
- Added migration `0004`, compact project/account/member administration, first-login password rotation, no-store one-time credentials, project/system audit, PI escalation/last-PI protections, and concurrent PI-removal serialization. Direct API checks passed; the Edge suite now passes 2 tests including admin/member/rotation workflow. Added three PostgreSQL integration tests; native pytest remains unavailable in this environment.
- Added migration `0005` with shared PostgreSQL rate windows for failed authentication and job/workflow/dataset writes. HMAC keys omit raw usernames/IPs, normal successful authentication does not spend failed-login quota, and rejected job requests create no row. Cross-engine, retry-header, per-account/source distinction and 2/2 Edge checks passed; native pytest remains unavailable.
- Added migration `0006` and persisted queue-wait/per-attempt execution distributions, plus bounded per-process HTTP status/duration metrics. Exact synthetic percentiles, HTTP status categories, sample cap and `/metrics` self-exclusion passed; the admin Edge health view shows these metrics. Native pytest remains unavailable.
- Added automated API restart and unavailable-database recovery regressions. Real dedicated Compose testing confirmed the static Nginx upstream broke when the API container IP changed; dynamic Docker DNS plus explicit `/api` rewrite fixes the proxy. API restart and real PostgreSQL stop/start both passed: 503 during outage, readiness recovery, queued job/idempotency persistence, and worker completion.
- Full local regression passes: 25 backend PostgreSQL tests, frontend production build, 390px Edge 2-test suite, migration `alembic check`, and dedicated two-worker Compose readiness.
- GitHub Actions run `45525441466` passes backend, frontend and compose in private repository `hwen020/researchhub`. Public visibility, v1 tag and Render deployment remain separate external gates.
- Created private independent repository `hwen020/researchhub` and pushed `main`. The first CI run exposed Ubuntu 26.04 incompatibility with Playwright 1.55.1; CI runner pins now use Ubuntu 24.04 and a fixed rerun is in progress. No public setting or v1 tag has been applied.
- v1 release and public demo status are tracked in the [acceptance report](docs/test-report-v1.md).
