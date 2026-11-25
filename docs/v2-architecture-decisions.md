# ResearchHub v2 architecture decisions

## Durable scheduler

Use least-recently-dispatched project rotation. Within each eligible project, dispatch by capped priority plus age. PostgreSQL persists the dispatch sequence on each project. A schema-scoped advisory transaction lock serializes admission, quota changes and lease reservations. Plugin computation and lease heartbeats do not take that lock. The job row and lease token remain the source of truth for reservation ownership.

## Demo profile

Use a fixed synthetic genomics DAG and a read-only guest. The guest can inspect the fixed project, dataset and results. Prior fixture credentials cannot authenticate in demo mode. Keep the profile isolated from full local deployment. The project IDs and guest identity are fixed; the stored synthetic dataset can be reconstructed by checksum when the demo filesystem disappears.

## Release isolation

Development is local on `feature/researchhub-v2`. Main and the v1 tag are release references. The v2 candidate explicitly links the service to main and disables commit-triggered service deploys. Blueprint auto-sync remains an independent Render setting. Verify the existing service and Blueprint in the authenticated dashboard before deploying.

[Render Blueprint specification](https://render.com/docs/blueprint-spec)
