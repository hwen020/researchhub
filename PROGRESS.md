# Progress

- Resumed from handoff checkpoint `4df71f9`; committed Edge/mobile fixes as `c836a41` and audited administration as `5174185`.
- Added incremental migrations for run manifests, audit and worker heartbeats.
- Native PostgreSQL tests exercise concurrent claims, stale results, worker process loss, funding consistency, API isolation and dataset provenance.
- Recorded native 1/2/4-worker runs using real authenticated HTTP submissions.
- Added a Compose browser fixture and a GitHub Actions workflow.
- Fixed the Edge Basic-auth challenge that blocked SPA login errors and resolved a 390px audit-content overflow. The full mobile Edge browser flow passes (1 test); frontend production build passes. Added a PostgreSQL auth-response regression test, with direct API response behavior verified through the isolated Compose stack.
- Added migration `0004`, compact project/account/member administration, first-login password rotation, no-store one-time credentials, project/system audit, PI escalation/last-PI protections, and concurrent PI-removal serialization. Direct API checks passed; the Edge suite now passes 2 tests including admin/member/rotation workflow. Added three PostgreSQL integration tests; native pytest remains unavailable in this environment.
- Added migration `0005` with shared PostgreSQL rate windows for failed authentication and job/workflow/dataset writes. HMAC keys omit raw usernames/IPs, normal successful authentication does not spend failed-login quota, and rejected job requests create no row. Cross-engine, retry-header, per-account/source distinction and 2/2 Edge checks passed; native pytest remains unavailable.
- v1 release and public demo status are tracked in the [acceptance report](docs/test-report-v1.md).
