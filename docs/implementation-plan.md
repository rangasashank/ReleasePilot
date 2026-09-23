# ReleasePilot implementation roadmap

Source: the agreed September 6 implementation plan and product specification. Work one phase at a time: explain the key idea, build a visible slice, run focused checks, and recap. Assume full-stack experience; concentrate learning on the unfamiliar architecture. Avoid extra tutorial sessions.

**September 10 status:** The local implementation and AWS deployment assets are complete for portfolio review. At your request, the remaining build phases were implemented together; use the [learning companion](learning-companion.md) to revisit them in smaller sessions. Live authenticated provider checks and AWS deployment remain deferred. See the [verification record](verification.md) for measured results and limits. The phase descriptions below preserve the original learning sequence.

| Phase | Deliverable | Main learning checkpoint |
| --- | --- | --- |
| 1 | Authenticated dashboard, service persistence, migrations, Compose, initial CI | Trace session-derived workspace authorization from browser to database. |
| 2 | Normalized evidence, deterministic policy engine, three fixture reports | Failed required CI blocks; unknown evidence never means success. |
| 3 | GitHub OAuth/App connection, ref resolution, real comparison | Distinguish identity, installation authorization, refs, and SHAs. |
| 4 | Real PR/review/check evidence and deterministic report | Interpret current provider state and required-check policy conservatively. |
| 5 | Outbox, SQS worker, leases, checkpoints, polling, retries | Duplicate delivery produces one durable logical result. |
| 6 | Rate-limit coordination, Redis cache, signed durable webhooks | Caches are disposable; snapshots are immutable; events may reorder. |
| 7 | Versioned Markdown/text/PDF ingestion and object storage | Activate only complete document versions and preserve historical citations. |
| 8 | pgvector + full-text hybrid retrieval and cited excerpts | Scope before ranking and measure recall@5. |
| 9 | Six typed read-only MCP tools over existing services | Tool schemas do not replace authorization and output bounds. |
| 10 | Two specialists, final reviewer, durable typed handoffs | Parallel fan-out/fan-in, independent retries, budgets, deterministic scoring. |
| 11 | Complete UX, 18 evaluations, end-to-end checks, metrics | Evaluate failure handling and supported claims, not wording alone. |
| 12 | AWS containers/data/queue, observability, staging delivery | Reproduce deployment and recover from worker/deployment failure. |
| 13 | README, decision notes, short demo, measured resume claims | Explain the complete workflow and tradeoffs with evidence. |

## Defaults to preserve

- Next.js + FastAPI modular monolith, PostgreSQL source of truth, one workspace/repository, no production deployment actions.
- Session-derived ownership, server-only provider credentials, read-only tools, exact resolved SHAs.
- Category risk caps: CI 40, code/review 25, complexity 20, deployment documentation 15. Confidence threshold initially 75; GO also requires verified required checks and mandatory evidence. Version rules and label heuristics.
- Unknown required-check policy prohibits GO. Preserve prior failed attempts as flakiness evidence after a successful rerun. AI explains and proposes checklist items; Python owns points and recommendation.
- Add durable jobs before ingestion or AI. The delivered local setup uses PostgreSQL polling and local object storage, with Moto tests for S3/SQS adapters; LocalStack remains an optional later exercise. PostgreSQL owns jobs/checkpoints; Redis is never authoritative.
- Both specialists start from a deterministic component summary. Persist follow-up evidence and freeze the reviewer's evidence manifest after both specialists finish.
- Enforce ten follow-up MCP calls globally, six for Change/CI, four for Knowledge, zero for Reviewer; one structured repair per agent.
- Version documents and preserve captured citations when active documents change. Filter retrieval by workspace/service before hybrid ranking; top five by default.
- Grow tests with every feature. Routine CI uses deterministic tools/models; live-model evaluations run separately.
- Defer Terraform, Jira, Slack, CloudWatch product evidence, invitations, custom policies, and multi-repository support until required scope is complete.

## Phase completion gate

Each phase needs a visible demonstration, tests, error states, and a short learning/documentation update. Do not mark the whole project resume-ready until every required item in specification sections 4 and 30 is verified. Phase 1 and Phase 2 are implemented. Current stop: explore the three fixture reports and review the pure scoring function before connecting GitHub in Phase 3.
