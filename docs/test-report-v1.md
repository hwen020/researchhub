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
| GitHub Actions | IN PROGRESS against the private independent repository `hwen020/researchhub`. The first Ubuntu 24.04 rerun is being observed after the first runner failure was fixed. Public repository and v1 tag remain blocked until CI passes and the license gate is confirmed. |
| Public demo | NOT DEPLOYED. Render login/authorization was unavailable in the current browser session, and no existing Render service was modified. Render Free demo feasibility and public guest isolation remain open. |

See [development handoff](../DEVELOPMENT_STATUS.md) for remaining release work.
