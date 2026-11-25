# ResearchHub - Research Cyberinfrastructure and Durable Scientific Workflows

## Resume bullets

- Extended a PostgreSQL durable job queue with transactionally enforced project quotas, least-recently-dispatched fairness, priority aging and capability-aware Worker matching.
- Built immutable DAG versions, conditional execution, partial reruns and persistent schedule reconciliation, with provenance linking datasets, parameters, attempts and output digests.
- Orchestrated Genomics and Wearable Mobility pipelines under one Worker and dataset interface, producing reproducible synthetic Spearman/FDR reports and screened CSV/GeoJSON mobility exports.
- Implemented lease-fenced artifact intents, conditional S3 publication and reconciliation after database rollback, and verified results against PostgreSQL and VersityGW.
- Added persistent notification replay, execution correlation and a React workbench for project quotas, scientific workflows and artifacts.

## LinkedIn project description

ResearchHub is an open-source research computing workbench for running reproducible scientific analyses through an independent scheduler and durable PostgreSQL Workers. The v2 development branch adds equitable project scheduling and resource limits, versioned and conditional DAGs, reusable scientific artifacts, and dataset-backed Genomics and Wearable Mobility pipelines. The work demonstrates transaction design, failure recovery and reproducibility through isolated PostgreSQL, object-store and browser acceptance.

## Five-minute demo

| Time | Show |
| --- | --- |
| 0:00-0:45 | Show the project and Resources view. Explain logical CPU and memory units, concurrent leases and bounded admission. |
| 0:45-1:45 | Open a versioned synthetic dataset, submit the matching research workflow and show its dataset SHA-256. |
| 1:45-2:45 | Follow the dependent stages in Workflows, then download the final report and provenance document. |
| 2:45-3:45 | Open Artifacts and explain how a PostgreSQL intent survives an interrupted object publication. Show the S3 rollback test in CI. |
| 3:45-5:00 | Show project notification history and read state. Compare an original failed workflow with a rerun to explain reused nodes. |

## Fifteen-minute system design interview

| Time | Discussion |
| --- | --- |
| 0-2 min | Define project boundaries, immutable dataset versions, allowed scientific computation and durable results. |
| 2-5 min | Explain admission and serialized reservations, fair dispatch across eligible projects, capped priority aging and the throughput trade-off. |
| 5-8 min | Walk through lease expiry, token fencing, conditional DAG decisions, partial reruns and trigger deduplication. |
| 8-11 min | Distinguish source commits from object publication. Describe staged bytes, preconditioned writes, checksum verification and unknown-outcome retries. |
| 11-13 min | Explain notification cursor ordering and per-account read state. Follow correlation IDs without exporting high-cardinality labels. |
| 13-15 min | Discuss measured scaling on one host, the boundary between logical capacity and isolation, and how a real remote executor would be qualified. |

## Role alignment

For Research Software Engineer roles, lead with scientific methods, immutable dataset inputs, validated exports, lineage, reproducibility and the careful reuse of licensed scientific code.

For Backend and Distributed Systems Engineer roles, lead with PostgreSQL transaction boundaries, fixed ownership tokens, backpressure, fairness, replayable events, and fault-injection evidence. Independent Workers on one host demonstrate concurrent coordination and process recovery.
