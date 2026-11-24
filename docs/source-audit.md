# Source audit

| Source | Evidence | Finding |
| --- | --- | --- |
| [Chat-Demo](https://github.com/hwen020/Chat-Demo) | Local clean checkout at `5117a166993c3380448822cec9d1f441ad8bfca2` | Messenger's `apps/messenger/api/app/realtime.py` publishes best-effort Redis wakeups. The API's `main.py` handles idempotency conflicts and periodic replay. PostgreSQL migrations, Nginx configuration and integration tests are present. No tracked license was found. |
| [Aging Genomics Lab](https://github.com/hwen020/aging-genomics-lab) | GitHub public main tree | MIT project code under `src/aginggenomics`, fixtures under `data/demo` and scientific tests under `tests`. Source retrieval from the execution environment failed. SHA and module-level compatibility remain unverified. |
| [Wearable Mobility Research Pipeline](https://github.com/hwen020/wearable-mobility-research-pipeline) | GitHub public main tree | MIT application code under `app`, with FastAPI, SQLAlchemy, migrations and tests. SHA and module-level compatibility remain unverified. |
| [Travel Desk](https://travel-desk-demo.onrender.com/) | No local checkout located | Source repository, license, approval snapshot implementation and test coverage unverified. |
| [Enterprise Operations AI](https://github.com/hwen020/enterprise-operations-ai) | Supplied public URL unavailable in this session | Source, commit and public redistribution rights unverified. |
| Ads Attribution Pipeline | No local checkout located | Deduplication and consistency modules unverified. |

The new repository has an independent Git history. Existing checkouts were inspected read-only.
