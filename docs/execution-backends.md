# Execution backends

The contract exposes submit, poll, cancel, health, capabilities and job resource requirements. The active local backend starts fixed registry plugins in independently managed Python subprocesses. Worker heartbeat, attempt deadlines, cancellation and result publication are governed by the PostgreSQL lease and fencing token.

The local backend reports logical units and process availability. Host CPU or memory isolation requires a future enforcing backend. An eventual container driver must use trusted images, a restricted filesystem and bounded resources. A Slurm adapter would need a real account, controller connection and tests for submission, idempotency, polling and cancellation. The current stack runs independent processes on one host.
