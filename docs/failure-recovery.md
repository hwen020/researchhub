# Failure recovery

The PostgreSQL integration test starts a process that persists a real job lease, kills it, starts an independent worker and waits for attempt two to publish. It verifies that the old token cannot overwrite the result. The scheduler test terminates the scheduler after root enqueuing, restarts it, and checks that the original roots and their downstream job reach success.

The queue also has deterministic tests for retry exhaustion, fencing and cancellation order. The benchmark repeats the process-loss case at one, two and four worker counts. [Benchmark results](benchmarks.md).
