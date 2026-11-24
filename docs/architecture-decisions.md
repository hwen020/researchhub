# Architecture decisions

## Independent repository

The available Messenger checkout does not provide a verified redistribution grant. The preferred administrative projects could not be inspected. Use a clean foundation and preserve precise provenance when a candidate module is approved for reuse.

## PostgreSQL queue

Keep submission, idempotency keys, attempts, events and results within one transaction boundary. Workers claim rows using `FOR UPDATE SKIP LOCKED` and renew a short lease. The attempt token fences stale workers. A lease can expire before its worker stops, so execution is at least once. Only the active attempt can commit the authoritative result.

## Process boundaries

The API authorizes access and writes durable state. Workers execute allowlisted plugins. The scheduler will materialize ready DAG nodes from persisted dependency state. Separate processes can scale independently while sharing a database and application code.
