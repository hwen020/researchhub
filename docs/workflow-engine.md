# Workflow engine

The scheduler validates definitions as directed acyclic graphs and stores a definition snapshot and topological order with each run. Independent roots are queued in the same reconciliation transaction. Descendants wait for upstream success. Upstream failure or cancellation marks descendants blocked. Advancing a run and enqueuing ready jobs commit together. A scheduler restart rereads persisted state and uses deterministic idempotency keys for each run node.
