# v2 development acceptance

Phases 0 through 3 were exercised using Python 3.12 in an existing ResearchHub Linux image and PostgreSQL 16 in the dedicated acceptance stack. Tests created isolated PostgreSQL schemas. The backend snapshot reported **33 passed and 3 subtests passed**. Warnings came from Starlette TestClient and Alembic configuration deprecations. TypeScript and the Vite production build passed separately.

| Area | Evidence |
| --- | --- |
| Scheduling | Concurrent reservations respected project limits, and three queued projects received leases. PostgreSQL tests exercised priority aging, capability and resource matching, saturated admission and idempotent replay. |
| Recovery | Existing PostgreSQL regressions exercised abrupt worker termination, a second attempt, fencing, an API restart and database connectivity interruption. |
| Advanced workflows | Parallel roots, cycles, conditions, finalization, immutable versions, reused upstream results, scheduled trigger deduplication, cancellation, snapshot migration and lineage. |
| Migrations | A populated v1 schema upgraded from 0006 to 0008. The old workflow stayed executable and Alembic reported no model drift. |
| Genomics | A fixed read-only guest profile seeded a dataset-backed DAG. Two independent workers and a scheduler ran against PostgreSQL. JSON, CSV and a versioned run manifest downloaded through the authorized API. Prior fixture administrator credentials were rejected. |
| Wearable mobility | Two workers and a scheduler completed all five stages. The synthetic CSV reported three samples, 60 steps, 0.111 km of screened distance and one speed outlier. The GeoJSON route contained the first two points. The manifest linked the dataset and upstream output hashes. |

The first v2 checkpoint ran on an isolated Compose stack with PostgreSQL, API, scheduler, frontend and two Worker containers. Both 390 px Edge tests passed. All three cloud CI jobs passed for the same checkpoint. [GitHub Actions 45544377608](https://github.com/hwen020/researchhub/actions/runs/45544377608).

The storage snapshot passed 34 default PostgreSQL regressions with the S3-only case skipped in that run. A separate invocation passed that case using a real VersityGW v1.7.0 process. The server returned 412 on a replay after database rollback. The test verified exact bytes, pending recovery after connection refusal, old unreferenced object removal and unavailable referenced bytes.

The live v1 readiness endpoint returned HTTP 200 during baseline inspection. Public genomics, authenticated Render settings and v2 benchmarks are tracked in the acceptance matrix.

## v2 integration checkpoint

- Final candidate SHA `ee41b1b0ec5b40bc97347629df9618350e93b241` passed [GitHub Actions run 45553387895](https://github.com/hwen020/researchhub/actions/runs/45553387895): backend, frontend and compose, including three 390 px browser scenarios and the fixed Genomics demo image smoke test.

- The local Python suite completed 36 tests across real PostgreSQL and VersityGW, including versioned workflows, notification replay, quota/admission regressions and S3 consistency.
- The full local 390 px Edge pass covered three scenarios against the migrated two-Worker Compose stack. The new scenario registered and uploaded the synthetic Mobility dataset, ran the five-stage DAG, opened provenance and the artifact registry, and verified persistent notification read state.
- A separate repeatable test terminated the real VersityGW process and restarted it on the same backend directory. PostgreSQL retained the PENDING intent during the outage, and the publisher verified and served the exact staged bytes after restart.
- The pipeline enabled cloud smoke testing of the actual Render-compatible image with a separate disposable PostgreSQL database.
- [Benchmarks](benchmarks-v2.md), [deployment gates](deployment-v2.md) and [source audit](privacy-audit-v2.md).
