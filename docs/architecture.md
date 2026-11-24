# Architecture

```mermaid
flowchart LR
    Browser --> Proxy[Nginx / Vite]
    Proxy --> API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> Artifacts[(CSV volume)]
    Scheduler --> DB
    Workers --> DB
    Workers --> Plugin[Allowlisted plugin subprocess]
```

The API exposes project-scoped jobs, datasets, funding, audit and workflow operations. A project belongs to an organization. PostgreSQL stores project membership and operational state. The scheduler and workers publish through PostgreSQL transactions. Independent worker processes use the same image and accept work concurrently.
