# Source audit

The inspection used existing local checkouts and public-repository mirrors. The ResearchHub history starts with its own root commit.

| Source | Inspected revision | Evidence and outcome |
| --- | --- | --- |
| [Chat-Demo](https://github.com/hwen020/Chat-Demo) | Local Messenger checkout `5117a166993c3380448822cec9d1f441ad8bfca2`; public inventory mirror `14142edc6af25aa56c3b5b91806d1677da21091a` | Database-backed replay, Redis wakeups and idempotency shaped the architecture. No source transferred. |
| [Travel Desk](https://github.com/hwen020/travel-desk-demo) | `f337cf68c1c11dc93ccc38fac78a963f283c0660` | Inspected `workflow.py` role actions, approvals and settlement boundaries, plus `policies.py` and workflow test inventory. No tracked license identified. |
| [Enterprise Operations AI](https://github.com/hwen020/enterprise-operations-ai) | `31418b018c90c3e88ac131407a3754dc517a13d7` | Inspected public mirror's MIT license, demo server and `operations/` module inventory. |
| [Aging Genomics Lab](https://github.com/hwen020/aging-genomics-lab) | `79522083661d35509f3808d7fd9bd494f250001b` | Inspected `src/aginggenomics/analysis.py`, test inventory and MIT terms. Extracted age associations and false-discovery-rate adjustment. |
| [Wearable Mobility Research Pipeline](https://github.com/hwen020/wearable-mobility-research-pipeline) | `82cd2f3b9f051c7a0c51fe803f592eae3f77e845` | Inspected `app/analytics.py`, pipeline and test inventory, and MIT terms. Mobility integration is pending. |
| Ads Attribution Pipeline | No verified local source | No reuse claimed. |

The pre-public audit found no private path, private email, credential, private key or GitHub token in tracked content. The tracked Aging Genomics MIT notice is preserved. ResearchHub itself lacks a top-level license file, so public release remains blocked until the project owner confirms the public license and notice.
