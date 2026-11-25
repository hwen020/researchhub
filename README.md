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

## Release verification status

The current 390px Edge browser suite passes 2 tests, the frontend production build passes, migration metadata is clean through the current head, and the dedicated PostgreSQL backend suite passes 25 tests. GitHub Actions run `45525441466` passed backend, frontend and compose; public repository, tag/release and public demo deployment remain separate publication gates.

## License

ResearchHub's original implementation is licensed under the MIT License in [LICENSE](LICENSE). Third-party notices and source attribution are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The Aging Genomics MIT license remains in [docs/aging-genomics-LICENSE.txt](docs/aging-genomics-LICENSE.txt). The license applies only as documented and does not relicense any inspected third-party work.

## Tests

From `backend`, install `requirements-dev.txt`. Set `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE` to a disposable PostgreSQL database and run `alembic upgrade head`, `alembic check` and `python -m pytest -q`. From `frontend`, run `npm ci` and `npm run build`. Browser smoke tests use Playwright against an isolated Compose stack with synthetic fixture accounts.

## Deployment status

The full stack runs locally in Compose. Public guest deployment and official release status are tracked in the acceptance report. The current filesystem adapter requires a persistent artifact volume.
