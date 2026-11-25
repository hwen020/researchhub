# Progress

- Preserved the prior work in local development checkpoint `45453a1`.
- Added incremental migrations for run manifests, audit and worker heartbeats.
- Native PostgreSQL tests exercise concurrent claims, stale results, worker process loss, funding consistency, API isolation and dataset provenance.
- Recorded native 1/2/4-worker runs using real authenticated HTTP submissions.
- Added a Compose browser fixture and a GitHub Actions workflow.
- Fixed the Edge Basic-auth challenge that blocked SPA login errors and resolved a 390px audit-content overflow. The full mobile Edge browser flow passes (1 test); frontend production build passes. Added a PostgreSQL auth-response regression test, with direct API response behavior verified through the isolated Compose stack.
- v1 release and public demo status are tracked in the [acceptance report](docs/test-report-v1.md).
