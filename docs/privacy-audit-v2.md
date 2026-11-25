# v2 source and publication checks

The audit covered the researchhub repository and the development branch. The scan checked 21 reachable commits at the preceding checkpoint for private-key headers, GitHub/AWS credential patterns and private Windows paths. That scan returned zero file matches. All reachable author and committer identities used the intended GitHub noreply identity. Tracked files exclude runtime environment files, local databases, browser dumps, runtime credentials and generated dependencies.

GitHub reported the existing public v1.0.0 release and no pull requests or uploaded Actions artifacts at the time of review. Main remained at `b7afbbe`, and the v1.0.0 tag still peeled to `63532a9`. History remains reachable and was never rewritten during this development. The known historical fixture credentials are for synthetic fixtures. The v2 demo authenticates only its fixed guest and blocks mutation.

The original ResearchHub MIT license and the Aging Genomics MIT notice remain preserved. Mobility routines retain the upstream MIT notice and exact source commit and path attribution. The VersityGW process used for acceptance was a separately downloaded verified upstream release and is outside the ResearchHub source distribution.

The release gate also requires the authenticated Render service and Blueprint settings, the final cloud CI result and public workflow smoke evidence. See [deployment modes](deployment-v2.md).
