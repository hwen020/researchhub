# Render Free demo status

## Full deployment mode

ResearchHub's complete deployment keeps PostgreSQL durable, uses independent scheduler and worker services, and uses a persistent artifact volume. Render Free web services are unsuitable for that architecture because they spin down after inactivity, lose local filesystem changes across restarts/deploys/spindown, and cannot attach persistent disks. Free Postgres expires after 30 days and has no backup support. Free services do not provide an independent background-worker service.

## Safe Demo Mode

A separate demo profile would need explicit limits and no claim of production durability:

- Public restricted guest accounts only, with synthetic data and no private artifacts.
- PostgreSQL persistence in a clearly disclosed temporary Free database, with an in-app demo reset boundary.
- Real plugin execution in a bounded API process or a single low-concurrency demo worker, not a pretended independent worker cluster.
- No public write of private code, datasets or credentials.
- No persistent artifact claim for filesystems; only synthetic in-memory or temporary demonstration outputs.
- HTTPS, mobile browser validation, guest isolation and documented 30-day/15-minute/ephemeral limitations.

## Current attempt

- Independent repository: public at `https://github.com/hwen020/researchhub`.
- Render account: authenticated dashboard session is available.
- Render CLI: not required for the browser-created independent blueprint.
- Local demo validation: `demo/Dockerfile` built successfully with existing Docker cache. A temporary PostgreSQL database and container passed `/api/readyz`, synthetic login, browser Overview/Jobs, queued submission and worker `SUCCEEDED` state with a real synthetic summary result.
- Temporary container, database and validation image were removed.
- Live deployment: https://researchhub-demo.onrender.com
- Blueprint sync: `exs-dc348ee8bjmc73egsr90`; Web service `srv-dc34923rjlhs73en2ft0`; commit `1c18d22`.
- Public HTTPS readiness: PASS, `/api/readyz` returned `{"status":"ready"}`.
- Public browser login: PASS with the synthetic `fixture-pi` account.
- Public task execution: PASS. A real `summary@1` job reached `SUCCEEDED` with attempt 1 and synthetic result count 3, min 1, max 3, mean 2 and sample variance 1.
- Public Jobs view: PASS; Details, Manifest, JSON and CSV actions were present.
- No existing Render service was modified and no paid resource was purchased.
