# Reuse matrix

| Candidate | Source path and revision | Disposition | Target | Effort and risk |
| --- | --- | --- | --- | --- |
| Messenger persistence and wakeup separation | `apps/messenger/api/app/realtime.py` and `main.py`, `5117a166993c3380448822cec9d1f441ad8bfca2` | Pattern reference. Redistribution permission unverified. No code imported. | PostgreSQL queue and persisted events in `backend/researchhub/queue.py` | Medium. Worker leases need new concurrency semantics. |
| Age-association analysis | `src/aginggenomics/`, public main, SHA unverified | MIT candidate. Review exact revision, dependency footprint and attribution before adapting. | Scientific plugin, pending | Medium. Isolate analytical routines from UI and downloads. |
| Mobility validation and export | `app/`, public main, SHA unverified | MIT candidate for v2. Review exact revision, transitive licensing and spatial schemas. | Mobility plugin, pending | Medium. Ensure deterministic exports and bound input sizes. |
| Travel Desk and Enterprise Operations AI | SHA and paths unverified | Source access and redistribution rights pending. | Finance and workspace, pending | High until module boundaries and test coverage can be inspected. |
| Ads Attribution Pipeline | SHA and paths unverified | No reuse credited. | None | Unknown. |

Direct reuse and adapted code are both currently empty. No reuse savings have been measured.
