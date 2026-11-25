# Next steps

Resume on `feature/researchhub-v2` using the latest local commit shown by `git log -1 --oneline`. The [acceptance matrix](docs/v2-acceptance-matrix.md) separates current results and outstanding gates.

1. Connect scientific artifact staging and reconciliation to the dataset and result paths. Test the S3 adapter against a disposable compatible service.
2. Extend event-derived observability and benchmark mixed research workloads. Add persistent notification replay and a local execution backend interface.
3. Recheck the browser suite at 390 px, actual multi-worker Compose, migrations, CI, privacy, licenses and Render branch/sync settings before release.

From `backend` with a ResearchHub-only PostgreSQL test database configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`, run:

```sh
python -m pip install -r requirements-dev.txt
alembic upgrade head
alembic check
python -m pytest -q
```

From `frontend`, reuse installed dependencies and run `npm run build`. Run `npm run test:e2e` against a dedicated local stack with the synthetic browser fixture and `RESEARCHHUB_BROWSER_CHANNEL=msedge` when using Edge.
