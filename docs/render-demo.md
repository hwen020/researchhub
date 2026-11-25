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
- Live deployment: pending blueprint creation and public HTTPS acceptance in the authenticated Render account. No existing Render service is to be modified and no paid resource will be purchased.
