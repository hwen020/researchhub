# ResearchHub v2 acceptance matrix

| Area | Current evidence | Remaining |
| --- | --- | --- |
| Baseline isolation | PASS - Main contains accepted v2 at `ee41b1b`, v1 tag points to `63532a9`, and v1 release remains published | Authenticated Render account/dashboard verification remains external |
| Demo | PASS locally - Read-only fixed guest and five-stage synthetic Genomics pipeline passed the CI demo image | Public v2 deployment not changed without authorized dashboard access |
| Scheduler | PASS - 36-test suite and mixed benchmark covered reservation, aging, matching, backpressure and Jain fairness | Eight-Worker scaling remains unmeasured |
| Workflow | PASS - Fixed versions, conditions, rerun, schedules, cancellation and lineage passed | Longer public schedules remain out of scope |
| Research | PASS - Both pipelines passed local and cloud smoke; Mobility exports and provenance passed | Public V2 pipeline requires controlled Render deployment |
| Storage | PASS - Local and VersityGW S3 proved conditional writes, rollback, orphan cleanup and restart recovery | Dedicated public object-store stress remains local-only |
| Operations | PASS - Metrics, trace IDs, replay and read receipts passed local/CI | Prometheus/Grafana runtime qualification remains optional |
| Migrations | PASS - Schema 0012 upgrade and no-model-drift checks passed | Production backup remains an operator gate |
| Browser and Compose | PASS - Three 390 px browser scenarios passed locally and in [CI run 45553387895](https://github.com/hwen020/researchhub/actions/runs/45553387895) | None |
| Performance | PASS - Reproducible 1/2/4 observations and 0.960 mixed fairness recorded | S3 latency sweep and eight-Worker case unmeasured |
| Release | PARTIAL - Final CI green and existing v1 release retained; public Render settings require authenticated verification | Render deploy, tag/release and public v2 smoke |

[Local test evidence](test-report-v2.md). [Benchmarks](benchmarks-v2.md).
