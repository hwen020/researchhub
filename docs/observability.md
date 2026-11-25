# ResearchHub observability

The API assigns `X-Request-ID` and propagates it to enqueued jobs and workflows. Worker logs include correlation, run and attempt identifiers. Artifact publication logs include the same correlation. Logs record structured event metadata and omit credentials, payloads and query strings.

The administrator's JSON metrics show queue wait, attempt durations, per-project queue depth, failure classifications, workflow completion, artifact publication, stored managed bytes and lease recovery delay. Samples cover the last 24 hours with a limit of 20,000 per distribution. Lease recovery is the time from the retry transition to the replacement claim. Historic runs without creation timestamps are excluded from workflow timing.

The Prometheus exposition uses bounded state labels and contains no job, workflow, account or project IDs. Fetch it using platform-administrator Basic authentication or configure a scrape-only token file. Set `RESEARCHHUB_METRICS_TOKEN_FILE` to an untracked file containing a random token and set a local `GRAFANA_ADMIN_PASSWORD`.

```sh
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d
```

Grafana binds to localhost. Prometheus uses the token over the private container network and retains two days of samples.
