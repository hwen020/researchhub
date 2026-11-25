# Research resource scheduler

Projects default to eight simultaneous attempts, 512 outstanding jobs, 32 logical CPU units and 32 logical memory units. An attempt consumes resources from claim until its fenced terminal or retry transition. Cancellation requests retain the reservation until settled. No separate reservation counter needs repair after process or database loss. Expired attempts release resources when a worker recovers them.

Queue limits count queued, retrying and active jobs. This reserves space for retries even when concurrent submissions fill the queue. The system limit defaults to 10,000 outstanding jobs. Set `RESEARCHHUB_SYSTEM_QUEUE_LIMIT` consistently across API and scheduler processes. Job submission returns HTTP 429 and `Retry-After` on saturation. Replays of an existing idempotency key remain admissible. A DAG node can wait for capacity without creating a duplicate job.

Workers default to GENERAL and GENOMICS with 32 units of each resource. Configure `RESEARCHHUB_WORKER_CAPABILITIES`, `RESEARCHHUB_WORKER_CPU_UNITS` and `RESEARCHHUB_WORKER_MEMORY_UNITS` per worker. GEOSPATIAL and HIGH_MEMORY are matching labels. These units describe logical scheduling capacity. CPU and memory isolation require an execution backend that enforces operating system limits.

Authorized project members can read project quota and usage via `GET /projects/{project_id}/resources`. Platform administrators can update project quota via `PUT` and inspect online registrations at `GET /admin/workers`. The job list explains queue wait from current lease, quota and worker snapshots.
