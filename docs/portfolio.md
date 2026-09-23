# Portfolio presentation

## Resume wording you can use now

**ReleasePilot — Release readiness analysis platform**
*Next.js, TypeScript, FastAPI, PostgreSQL/pgvector, Redis, MCP, OpenAI API, Docker*

- Built a full-stack release-readiness application combining GitHub CI/review evidence and runbook retrieval into cited GO/CAUTION/NO_GO reports, with deterministic scoring and hard-blocker safeguards.
- Implemented a private MCP tool server, bounded analyst/reviewer orchestration, workspace-scoped hybrid retrieval, and resumable background jobs with leases, idempotency, transactional outbox, and S3/SQS adapters.
- Added automated policy/security evaluations, PostgreSQL migration tests, Docker integration checks, and prepared an ECS/RDS/S3/SQS deployment template with CI and manual ECR publishing.

Use the last bullet's “prepared” wording until you actually deploy and verify AWS. Do not claim production adoption, time saved, authenticated integration success, semantic-retrieval accuracy, or model-quality percentages from synthetic tests. Replace the third bullet with a measured outcome only after you have collected that evidence.

## Three-minute local demo

1. **Problem (20 seconds):** “A release manager has to assemble CI, reviews, changes and deployment guidance. This app captures them into one reviewable decision.”
2. **Workflow (40 seconds):** Open Release analysis, select Failed required CI, and submit. Show background progress, then the NO_GO report. Say explicitly that this is a credential-free synthetic scenario.
3. **Evidence (60 seconds):** Open the failed check citation; show its exact SHA and conclusion. Explain risk versus confidence. A known failed required check stays a blocker regardless of what an LLM says.
4. **Knowledge (30 seconds):** Upload the [sample runbook](../evals/documents/checkout-runbook.md) and search for rollback. Show the cited heading. Explain demo vectors versus the real embedding adapter.
5. **Engineering (30 seconds):** Expand agent/tool activity. Explain the two specialists, reviewer, read-only MCP scope, durable job lease, and retries. Show a test that rejects a foreign-workspace citation or unauthorized tool.
6. **Honest boundary (20 seconds):** “The local workflow is verified. The authenticated provider and AWS deployment paths are prepared; I have not used this on production releases.”

## Before pushing

Run the documented verification commands. Review `.gitignore`; keep `.env`, `.secrets`, databases, dependency directories and local artifacts out of Git. Follow the [hosted showcase setup](deploy-showcase.md) when you are ready to publish a live environment.

Suggested interview discussion: why SQL relationships preserve evidence lineage, why models and request schemas differ, why missing data cannot mean success, why an outbox is needed, how leases fence stale workers, and why the LLM never decides the hard blocker policy.
