# v1 acceptance report

The formal release gate remains open.

| Area | Result |
| --- | --- |
| Migrations | PASS for clean PostgreSQL schema through `0002`, development upgrade through `0003`, metadata comparison and Compose current-head schema job. A populated `0001` fixture verified a queued job and its project hierarchy survived the upgrade to `0003`. |
| Backend | PASS. 18 tests, two dependency deprecation warnings. Real worker kill/recovery, competing claims, duplicate submission, cancellation race, scheduler restart, budget serialization and project-scoped HTTP protection exercised. |
| Science | PASS for deterministic synthetic summaries and genomics associations. Manifest route checks dataset version, SHA-256, parameters and output checksum. |
| Performance | PASS. 1, 2 and 4 worker runs on one host. [Observed results](benchmarks.md). |
| Frontend build | PASS. TypeScript and production bundle built. |
| Compose | PASS for container startup with two workers and frontend readiness route. |
| Browser | FAIL on the first 390px Edge run. Sign-in error assertion timed out. Later browser assertions did not run. |
| GitHub Actions | NOT RUN. Workflow configured for backend, frontend, Compose and browser. |
| Public demo | NOT DEPLOYED. Guest profile and deployed validation remain open. |

See [development handoff](../DEVELOPMENT_STATUS.md) for remaining release work.
