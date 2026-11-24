# ResearchHub development handoff

## Release decision

v1.0 requires another development and acceptance pass. No official tag, release, public demo or v2 branch has been created.

## Verified work

- The original local development checkpoint is `45453a1`. GitHub's authenticated numeric user ID matched both configured Git noreply identities during a read-only check. The configured author name is `ellen-wen`.
- Added Alembic `0002` for run manifests, dataset provenance and project audit, then `0003` for persisted worker heartbeats. Upgraded the dedicated PostgreSQL development schema and ran `alembic check`. The development schema had zero application rows at the initial comparison. A separate populated `0001` schema retained its organization, project and queued job through `0003` and passed `alembic check`. The Compose schema job applied the current head from a new database.
- The latest native backend run passed 18 tests with two dependency deprecation warnings. Coverage includes real PostgreSQL concurrency, process-loss recovery, stale-token fencing, cancellation race, scheduler restart with two independent workers, budget consistency and HTTP project isolation. A TestClient exercised project-scoped dataset, audit and manifest routes. Scientific correctness and repeatability use synthetic inputs.
- Completed a native PostgreSQL 17.12 benchmark with 24 authenticated jobs per case, 4 concurrent submissions and 1, 2 and 4 independently launched workers. Recorded results in [benchmarks](docs/benchmarks.md).
- Built the React production bundle and started the isolated Compose project `researchhub-acceptance`, including two workers. The frontend proxy returned ready after startup. The first 390px Edge browser run reached the sign-in screen but timed out waiting for the invalid-credentials error. Full browser acceptance is pending.

## Resume order

1. Fix and rerun the browser sign-in regression in `frontend/tests/workspace.spec.mjs`. The HTTP Basic challenge on an invalid credential may be intercepting the browser response. After sign-in works, run the existing 390px test through roles, dataset versions, task details, manifest downloads, DAG status, funding and audit. Extend the fixture only where necessary to observe worker health, retries, failure and cancellation in the browser.
2. Complete remaining v1 release work from the original brief. Add ordinary authenticated project, team and membership administration with audited role changes. Add applicable API rate limiting, complete audit and security regression coverage, and expose job execution/queue waiting and HTTP duration metrics. Confirm project-scope handling for every download and administrative mutation. Add API restart persistence and real database outage recovery checks. Existing worker/process and benchmark checks need repeats only when a related implementation changes.
3. Push a development checkpoint to an independent repository and inspect actual GitHub Actions results. GitHub returned authenticated account information under approved network access and the target repository was absent at last check. No remote is configured yet. Run the privacy audit for reachable history, refs and all applicable GitHub surfaces before setting Public. Leave the version untagged until the release gate passes.
4. Provision an isolated free Render demo only after a restricted guest profile exists. The current Compose profile expects durable PostgreSQL and a persistent local artifact volume. Free Render web filesystem state is ephemeral, background workers are outside the available free service types, and free Postgres expires after 30 days. Verify HTTPS, real workflow execution, isolation, downloads, mobile and restart behavior against the deployed service. [Render Free limits](https://render.com/docs/free).
5. Finalize evidence-backed application materials and the five-minute walkthrough against the accepted v1 build. Published copies show November 26 at 4 p.m. Pacific for requisition #1038135. The official requisition page was not independently verified. [Illinois job portal](https://jobs.illinois.edu/). [Requisition mirror](https://www.highered360.com/jobs/JobDetail.cfm?JobID=179597240).

## Commands and environment

- Native suite from `backend` with the dedicated PostgreSQL endpoint configured in `DATABASE_URL` and `RESEARCHHUB_TEST_DATABASE`. Run `python -m pytest -q`. The test suite creates and removes its own PostgreSQL schemas.
- Browser setup uses `scripts/seed_browser_fixture.py`, which only seeds an empty database and reads the synthetic password from `RESEARCHHUB_FIXTURE_PASSWORD`. Set the same environment variable when running `npm run test:e2e` from `frontend`. The test base URL defaults to the Compose frontend at port 8080. Windows Edge uses `RESEARCHHUB_BROWSER_CHANNEL=msedge`.
- Docker Desktop's Linux engine responded through the named pipe with approved access. The read-only GitHub API probe also required approved network access. The default sandbox can deny each connection.
- Keep private interpreter paths, local data, environment files and fixture credentials outside tracked files.
