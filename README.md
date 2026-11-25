# ResearchHub

ResearchHub is a research operations and computing workbench. It combines project-scoped dataset versions, research budgets and reproducible analysis with a durable PostgreSQL queue, an independent DAG scheduler and separately scalable workers.

## Local Compose

Copy `.env.example` to `.env` and set a random alphanumeric `POSTGRES_PASSWORD`. Start the loopback stack with two workers.

```sh
docker compose up --build -d --scale worker=2
docker compose exec -e RESEARCHHUB_BOOTSTRAP_USER -e RESEARCHHUB_BOOTSTRAP_PASSWORD api python -m researchhub.bootstrap
```

Export a new bootstrap username and password in the invoking shell before running the bootstrap command. Open the workbench at `http://127.0.0.1:8080`. The API binds to `127.0.0.1:8000`.

## Engineering

- [Architecture](docs/architecture.md), [decisions](docs/architecture-decisions.md) and [consistency](docs/data-consistency.md)
- [Durable execution](docs/job-execution.md), [DAG scheduler](docs/workflow-engine.md) and [fault recovery](docs/failure-recovery.md)
- [Security](docs/security-model.md), [reproducibility](docs/research-reproducibility.md) and [source provenance](docs/reuse-matrix.md)
- [Acceptance report](docs/test-report-v1.md) and [measured benchmark](docs/benchmarks.md)

## v2 development

- [Resource scheduling](docs/resource-scheduler.md) and [fairness](docs/fair-scheduling.md)
- [Conditional workflows](docs/advanced-workflow-engine.md), [versions and schedules](docs/workflow-versioning.md) and [provenance](docs/research-plugin-interface.md)
- [Wearable mobility methods and exports](docs/mobility-workflow.md)
- [Artifact storage](docs/artifact-storage.md) and [publication consistency](docs/storage-consistency.md)
- [Observability](docs/observability.md), [v2 benchmarks](docs/benchmarks-v2.md) and [notification replay](docs/notification-delivery.md)
- [Execution backends](docs/execution-backends.md), [failure recovery](docs/failure-recovery-v2.md) and [deployment](docs/deployment-v2.md)
- [v2 test evidence](docs/test-report-v2.md) and [acceptance matrix](docs/v2-acceptance-matrix.md)

## Release verification status

The published v1.0.0 release passed 25 PostgreSQL backend tests and two 390 px Edge checks. The v2 candidate passed 36 local/CI-backend tests, three 390 px browser scenarios and all [GitHub Actions run 45553387895](https://github.com/hwen020/researchhub/actions/runs/45553387895) jobs. [v1.0.0 release](https://github.com/hwen020/researchhub/releases/tag/v1.0.0).

## License

ResearchHub's original implementation is licensed under the MIT License in [LICENSE](LICENSE). Third-party notices and source attribution are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The Aging Genomics MIT license remains in [docs/aging-genomics-LICENSE.txt](docs/aging-genomics-LICENSE.txt). The license applies only as documented and does not relicense any inspected third-party work.

## Public Demo Mode

Live public Demo: https://researchhub-demo.onrender.com

The repository includes an independent Render Free Demo blueprint in [render.yaml](render.yaml). It uses a Free Web Service and Free Render PostgreSQL database for synthetic demonstrations. The public instance passed HTTPS readiness, synthetic login, browser navigation and a real `summary@1` job: `QUEUED` to `SUCCEEDED` with attempt 1.

The Demo runs the existing API and a local demo worker/scheduler in one web instance. It is not a claim of the full distributed worker architecture or durable artifact storage. `/tmp` artifacts, Free web spin-down/restarter behavior and the 30-day Free PostgreSQL limit do not provide full Compose durability.

The v2 branch's `demo/Dockerfile` seeds a fixed read-only Genomics DAG. Its synthetic login is `demo-guest` / `synthetic-public-demo-only`. The public URL above still refers to the v1 deployment.

## Tests

From `backend`, install `requirements-dev.txt`. Set `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE` to a disposable PostgreSQL database and run `alembic upgrade head`, `alembic check` and `python -m pytest -q`. From `frontend`, run `npm ci` and `npm run build`. Browser smoke tests use Playwright against an isolated Compose stack with synthetic fixture accounts.

## Deployment status

The full stack runs locally in Compose. Public guest deployment and official release status are tracked in the acceptance report. The current filesystem adapter requires a persistent artifact volume.
