# Local multiprocess benchmark

Measured on Windows with an AMD Ryzen 7 5800H, 8 physical cores, 16 logical processors and 13.86 GiB RAM. PostgreSQL 17.12, CPython 3.11, one loopback FastAPI process and independently started native worker processes shared the same machine. Each case submitted 24 deterministic 64-observation summary jobs with four concurrent HTTP clients. Each result finalized on attempt one. This is a single run per case.

| Workers | Jobs | Submission concurrency | Jobs/s | Queue wait P95 ms | Completion P95 ms | API P50/P95/P99 ms | Killed holder to successful recovery ms |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 1 | 24 | 4 | 1.08 | 19625 | 20528 | 114.54 / 271.27 / 327.45 | 3813.88 |
| 2 | 24 | 4 | 2.03 | 9783 | 10735 | 118.38 / 296.14 / 347.72 | 3935.41 |
| 4 | 24 | 4 | 3.54 | 4784 | 5849 | 131.93 / 277.04 / 321.52 | 3694.16 |

Throughput includes the time from initial submission to the last observed success. Queue wait runs from creation to claim, and completion from creation to committed success. API latency includes authentication and commit. The recovery fixture takes a real lease in a separate process then terminates it and measures until another worker completes attempt two. It uses a 2.5-second attempt deadline and 250 ms initial retry backoff. This test is sensitive to Python subprocess startup and other activity on the host. With 24 submissions, the nearest-rank P99 is the maximum observation.

Install `backend/requirements-dev.txt`, set `DATABASE_URL` to a test PostgreSQL database with permission to create a schema, then run from `backend`.

```sh
python -m researchhub.benchmark --jobs 24 --concurrency 4
```
