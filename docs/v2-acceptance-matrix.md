# ResearchHub v2 acceptance matrix

| Area | Current evidence | Remaining |
| --- | --- | --- |
| Baseline | Base `b7afbbe`, local v1 tag, successful baseline Actions run `45531997808`, HTTP 200 from live readiness | Verify authenticated Render deploy and Blueprint settings |
| Demo | Read-only fixed guest and synthetic Genomics workflow pass locally against PostgreSQL and independent workers | Verify the candidate Render image and live deployment |
| Scheduler | PostgreSQL concurrency, three-project rotation, aging, capability matching, backpressure, cancellation and v1 recovery regressions pass | Benchmark mixed multi-project workload and run full Compose acceptance |
| Advanced DAG | Versioning, conditional branching, local rerun, scheduled deduplication, cancellation and provenance pass | Browser verification of the v2 panels |
| Research | Five-stage Genomics and Mobility DAGs finish with dataset lineage and authorized exports | Acceptance in final infrastructure profile |
| Migrations | Populated 0006 schema upgraded to 0008 with no drift and retained legacy workflow execution | Final current-head and downgrade validation |
| Observability | Queue saturation, project usage, worker availability and existing event metrics | Correlation, tracing, monitoring and new benchmarks |
| Object storage | Local and VersityGW S3. Real conditional PUT, connection failure, PostgreSQL publication rollback, retry, missing-object detection and orphan cleanup verified | Final infrastructure profile and full service stop/start test |
| Notifications and backends | Independent subprocess workers remain operational | Persistent notifications and unified backend contract |
| Release | TypeScript and production bundle passed locally | Public branch CI, final privacy and license audit, v2 release and Render update |

[Local test evidence](test-report-v2.md)
