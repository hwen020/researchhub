# Architecture decisions

## Independent monolith and process boundaries

The API owns authenticated mutations. The scheduler reconciles persisted workflow state and workers execute allowlisted research plugins. The three processes share one schema and can scale independently. This avoids a service network and separate schema ownership at the current workload.

## PostgreSQL queue

A single transaction covers submission, idempotency, lease state, result and events. PostgreSQL row locks coordinate claims. A Redis queue would require a reconciliation mechanism for messages and committed database state, so the current system has no broker. Work may execute again after a lease expires. The attempt token restricts authoritative publication to the active attempt.

## Dataset storage

Dataset data lives on a local artifact volume behind a storage adapter. Current Compose mode uses one API replica. Immutable metadata and SHA-256 pin inputs, and the filesystem and database have separate durability boundaries. Artifact garbage collection and cloud storage are future work.

## Public operation

Local Compose binds HTTP to loopback. Render's free web service and data retention constraints require a distinct guest experience and durable state design. [Render Free limits](https://render.com/docs/free).
