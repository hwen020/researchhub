# ResearchHub v2 acceptance matrix

| Area | Current evidence | Remaining |
| --- | --- | --- |
| Baseline isolation | Main at `b7afbbe`, v1 tag points to `63532a9`, v2 work on `feature/researchhub-v2` | Confirm authenticated Render settings |
| Demo | Read-only fixed guest and five-stage synthetic Genomics pipeline verified with PostgreSQL and independent Workers. Current public URL returned HTTP 200 once during baseline review | Verify current host settings, deploy accepted candidate and rerun the public smoke check |
| Scheduler | 36-test local suite exercises project rotation, aging, concurrent reservation, matching, cancellation, stale tokens and backpressure | Eight-Worker scaling only if host resources allow |
| Workflow | Fixed version binding, conditions, local rerun, scheduled trigger deduplication, cancellation and lineage passed | Per-workload stress with longer schedules |
| Research | Both five-stage pipelines finish with dataset and upstream provenance. Mobility exports test 0.111 km, 60 steps and one outlier | Public Genomics acceptance after controlled deployment |
| Storage | Local and VersityGW S3 verified for conditional writes, PostgreSQL rollback, missing-object detection, orphan cleanup, quota and actual S3 process stop/restart | Operate dedicated deployment-profile stress if required for release |
| Operations | Event metrics, trace IDs, project notifications, replay and read receipts. Local worker backend retains lease semantics | Prometheus/Grafana runtime qualification for optional monitoring |
| Migrations | Populated v1 schema upgrades to 0012 without model drift. Isolated mixed benchmark schemas install from empty | Back up before a production deployment |
| Browser and Compose | Three Edge tests at 390 px passed on an isolated two-Worker Compose stack with schema 0012 | Review exact final branch cloud run |
| Performance | Reproducible 1/2/4-Worker single and mixed observations. Mixed first-half Jain index 0.960 in three runs | S3 latency sweep and eight-Worker case |
| Release | Existing v1 Release and Demo address retained. Git history and branch identity reviewed | Final CI, authenticated Render verification and controlled tag/release/deploy |

[Local test evidence](test-report-v2.md). [Benchmarks](benchmarks-v2.md).
