# Next steps

Resume on `feature/researchhub-v2` using the latest local commit shown by `git log -1 --oneline`. The [acceptance matrix](docs/v2-acceptance-matrix.md) separates current results and outstanding gates.

1. Extend event-derived observability, add persistent notification replay and expose the local execution backend contract.
2. Benchmark mixed workloads. Repeat browser, multi-worker Compose and object storage fault tests on the final candidate.
3. Review migrations, cloud CI, privacy, licenses and Render branch/sync settings before tagging or deploying the release.

From `backend` with a ResearchHub-only PostgreSQL test database configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`, run:

```sh
python -m pip install -r requirements-dev.txt
alembic upgrade head
alembic check
python -m pytest -q
```

From `frontend`, reuse installed dependencies and run `npm run build`. Run `npm run test:e2e` against a dedicated local stack with the synthetic browser fixture and `RESEARCHHUB_BROWSER_CHANNEL=msedge` when using Edge.
