# v1 privacy and source audit

## Repository and history

- Audited HEAD and all reachable commits before public publication.
- No remote was configured before the independent-repository gate.
- All inspected commits use `ellen-wen` and the GitHub-verified noreply address `148025129+hwen020@users.noreply.github.com`.
- No private Windows path, private key, GitHub token, AWS key, private email, environment file, credential store or local secret was found in tracked files.
- `.env.example` contains placeholders only. Fixture passwords are synthetic CI values and must not be reused outside isolated test environments.
- No `node_modules`, frontend `dist`, Playwright test-results, pytest cache or coverage artifact is tracked.

## Source and license

- The Aging Genomics Lab MIT license is preserved at `docs/aging-genomics-LICENSE.txt`; `docs/reuse-matrix.md` documents the extracted statistics reuse and adaptation.
- Chat-Demo, Travel Desk and Wearable Mobility sources are design references or candidates only. No redistribution claim is made where redistribution rights were not verified.
- Travel Desk has no tracked license in the inspected source and was not reused as redistributed source.
- ResearchHub has no top-level project license file yet. It must not be published publicly until the owner confirms the project license and the final public-license notice.

## Release gate

- Private-source audit: PASS for tracked content and reachable commit identities.
- Private repository publication: permitted after final source audit.
- Private independent repository: CREATED and pushed at `https://github.com/hwen020/researchhub`; visibility remains private.
- GitHub Actions: run `45525441466` passed backend, frontend and compose for commit `d32c66c`.
- Public repository publication: BLOCKED until main-project permission/license is confirmed.
- GitHub Actions, public tag and Render demo remain separate from this privacy check.
