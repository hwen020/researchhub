# v1 acceptance report

The formal release gate remains open.

| Area | Result |
| --- | --- |
| Migrations | PASS for clean PostgreSQL schema through `0002`, development upgrade through `0003`, metadata comparison and Compose current-head schema job. A populated `0001` fixture verified a queued job and its project hierarchy survived the upgrade to `0003`. |
| Backend | PASS. 25 PostgreSQL integration tests. Coverage includes account rotation, project/member administration, shared API limiting, real event-derived metrics, worker kill/recovery, competing claims, duplicate submission, cancellation race, scheduler restart, API restart, PostgreSQL outage recovery, budget serialization and project-scoped HTTP protection. |
| Science | PASS for deterministic synthetic summaries and genomics associations. Manifest route checks dataset version, SHA-256, parameters and output checksum. |
| Performance | PASS. 1, 2 and 4 worker runs on one host. [Observed results](benchmarks.md). |
| Frontend build | PASS. TypeScript and production bundle built. |
| Compose | PASS for container startup with two workers, frontend readiness route, migration head and PostgreSQL recovery. |
| Browser | PASS. 2 tests passed in 390px Edge: existing project/job/DAG/dataset/download/funding/audit workflow and admin project/account/member/first-login rotation workflow. |
| GitHub Actions | PASS against public independent repository `hwen020/researchhub`. Run `45529021806` completed successfully with backend, frontend and compose all green for license commit `63532a9`. |
| Public demo | PASS for the isolated Free Demo at https://researchhub-demo.onrender.com. HTTPS readiness, synthetic login, browser Jobs view and real `summary@1` execution passed. This is a one-instance Demo profile, not the full persistent Compose architecture. |

See [development handoff](../DEVELOPMENT_STATUS.md) for remaining release work.
