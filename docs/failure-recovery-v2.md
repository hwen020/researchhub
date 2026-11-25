# v2 failure recovery

PostgreSQL persists queue state, dispatch order, workflow versions, schedules, artifact intents and notification cursors. Restart workers and the scheduler against the same schema to recover those records.

| Failure | Recovery and evidence |
| --- | --- |
| Lease holder terminates | Another Worker expires and retries the job. The old token cannot publish a result or stage an artifact. |
| Database connection interrupts | Readiness returns 503. API and workers resume once PostgreSQL accepts connections. The queue relies on committed rows. |
| Scheduler restarts | DAG runs retain their original version, and a due schedule advances with its run creation in one transaction. |
| Storage connection fails | A pending intent retains its bytes and retries. An existing object after a database rollback is verified before publication. |
| Reconnect after missed notifications | Fetch entries newer than the last seen cursor. Read receipts and event deduplication persist. |

[Acceptance observations](test-report-v2.md) distinguish process, connection and container tests.
