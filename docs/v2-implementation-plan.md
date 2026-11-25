# ResearchHub v2 implementation plan

1. Isolate development from main and secure the synthetic demo profile.
2. Extend the durable queue with transactional quota enforcement and persistent project rotation.
3. Add immutable DAG versions, conditional execution, local reruns, schedules and provenance.
4. Qualify the existing genomics workflow and verify the mobility source license before reuse.
5. Add S3-compatible artifact reconciliation, then observability, notifications and execution backends.
6. Run the full acceptance matrix and audit publication surfaces before tagging or deploying.

Use the existing PostgreSQL acceptance stack, images and frontend dependencies. Release evidence belongs in the acceptance matrix, with historical v1 results kept separate.
