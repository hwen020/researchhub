# v2 benchmark observations

Measured with CPython 3.12 and PostgreSQL 16.10 in Docker Desktop. The API, PostgreSQL, scheduler and independent Workers shared one Windows host. Each cell is one run. The workloads and runtime differ from the native PostgreSQL 17 v1 benchmark.

## Single-project summary workload

Twenty-four authenticated summary submissions, four concurrent clients and 64 deterministic observations per job. Completion ends at the fenced PostgreSQL result commit. The recovery case kills the separate process holding a short-lived lease and measures until a replacement succeeds.

| Workers | Jobs/s | Queue P95 ms | Completion P95 ms | API P50/P95/P99 ms | Kill to success ms | Speedup | Efficiency |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 1.42 | 14685 | 15390 | 135.82 / 185.10 / 200.08 | 3439.91 | 1.00 | 100% |
| 2 | 2.50 | 7526 | 8365 | 158.23 / 201.71 / 214.18 | 3605.51 | 1.76 | 88% |
| 4 | 4.41 | 3494 | 4212 | 176.84 / 208.32 / 225.22 | 3553.36 | 3.11 | 78% |

## Three-project mixed workload

Two summary submissions, two Genomics DAGs and two Wearable Mobility DAGs produced 22 jobs. Summary jobs varied priority and logical CPU demand. Completion includes the final workflow state. The scheduler published local artifact intents during the run. Workflow P95 describes four runs and equals the maximum observed completion time at this sample size.

| Workers | Jobs/s | Queue P95 ms | Workflow P95 ms | API P50/P95/P99 ms | Speedup | Efficiency | Jain index |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 1.17 | 3407 | 18435 | 231.76 / 259.79 / 259.79 | 1.00 | 100% | 0.960 |
| 2 | 2.33 | 1400 | 9181 | 168.59 / 200.15 / 200.15 | 1.99 | 100% | 0.960 |
| 4 | 2.95 | 577 | 7061 | 192.68 / 216.22 / 216.22 | 2.52 | 63% | 0.960 |

Fairness is Jain's index over the logical CPU units assigned to the three projects in the first 11 claims. The observed shares were 3, 5 and 4 units in each run. This reflects both eligibility and demand. It does not measure host CPU utilization or guarantee equivalent shares for other DAGs. Eight Workers, mixed-workload forced outages and object-store latency sweeps remain unmeasured.

From `backend` with `DATABASE_URL` targeting a dedicated PostgreSQL test database:

```sh
python -m researchhub.benchmark --jobs 24 --concurrency 4
python -m researchhub.benchmark_mixed --submissions-per-project 2
```
