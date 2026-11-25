# Reuse matrix

| Source and revision | Original path | Stack | Reuse | ResearchHub path | Cost or risk |
| --- | --- | --- | --- | --- | --- |
| Aging Genomics Lab `79522083661d35509f3808d7fd9bd494f250001b` | `src/aginggenomics/analysis.py` | NumPy, pandas, SciPy | MIT function bodies extracted for `age_association` and `benjamini_hochberg`. Imports adapted and license preserved. | `backend/researchhub/aging_statistics.py` with adapter in `plugins.py` | Adapter validates bounded data and supplies only the columns the functions need. No measured reuse savings. |
| Chat-Demo `5117a166993c3380448822cec9d1f441ad8bfca2` | `apps/messenger/api/app/realtime.py`, `main.py` | FastAPI, Redis, PostgreSQL | Design reference. Redistribution rights unverified. | Original persistent queue and history | Queue leases and fencing required new implementation. |
| Travel Desk `f337cf68c1c11dc93ccc38fac78a963f283c0660` | `workflow.py`, `policies.py` | Python, SQLite | Design reference. No redistribution grant located. | Original budget and request services | Finance consistency uses PostgreSQL row locking. |
| Enterprise Operations AI `31418b018c90c3e88ac131407a3754dc517a13d7` | `operations/domain.py`, `operations/rules.py` | Python | MIT candidate reviewed at module-inventory level. | None | Administrative demo domain differs from research budgets and memberships. |
| Wearable Mobility `82cd2f3b9f051c7a0c51fe803f592eae3f77e845` | `app/pipeline.py`, `app/analytics.py` | Python | MIT | Validation, daily summaries, edge screening and GeoJSON in `researchhub/mobility.py`. | [Reuse and limits](mobility-workflow.md) |

Original implementations include API authorization, project/member/account administration, funding, dataset registry, PostgreSQL shared rate limits, real execution/HTTP metrics, job queue, worker, scheduler, run manifests and React workspace. Third-party reuse covers the documented MIT aging-statistics and Wearable Mobility routines, with both licenses preserved. Travel Desk remains a design reference.
