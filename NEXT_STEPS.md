# Next steps

Resume on `feature/researchhub-v2` using the latest local commit shown by `git log -1 --oneline`. The [acceptance matrix](docs/v2-acceptance-matrix.md) separates current results and outstanding gates.

1. Confirm cloud CI for the latest feature-branch commit and use the acceptance matrix to finish its remaining gates.
2. In the authenticated Render dashboard, verify the existing service branch, deploy setting, Blueprint sync and free database state.
3. Merge and publish only after the release gates pass. Verify the public Genomics DAG and restricted guest behavior at the existing address.

From `backend` with a ResearchHub-only PostgreSQL test database configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`, run:

```sh
python -m pip install -r requirements-dev.txt
alembic upgrade head
alembic check
python -m pytest -q
```

From `frontend`, reuse installed dependencies and run `npm run build`. Run `npm run test:e2e` against a dedicated local stack with the synthetic browser fixture and `RESEARCHHUB_BROWSER_CHANNEL=msedge` when using Edge.
