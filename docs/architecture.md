# Architecture decisions and limits

## Evidence first, explanation second

Release refs resolve to full SHAs before a job is queued. Collection is bounded (80 GitHub requests, 300 comparison files, limited commit/PR pagination); incomplete collection remains explicit. Required check identities include GitHub App IDs where available. Unknown policy, ambiguous identities and unavailable endpoints cannot establish passing required checks. Diverged/backward ranges are rejected.

The worker captures normalized evidence before analyst fan-out. MCP tools read this sealed evidence rather than asking each agent to fetch GitHub independently. This gives each specialist the same input and makes an old report reproducible. Runbook retrieval is scoped by workspace and service before vector/full-text ranking. Citations reference captured excerpts, so later document removal or reindexing does not rewrite history.

## Boundaries around AI

Two specialists work independently; the reviewer sees their handoffs. The private MCP server validates signed workspace/analysis/role/lease context, role allowlists, repository/service/SHA arguments, and budgets. The model cannot provide its own credentials or expand its permissions. C rejects unsupported claims, and application code rejects citations with foreign IDs, empty quotes, or text not present in captured excerpts. Quote existence is not a formal proof of semantic entailment; reviewing quality still needs live-model evaluation and human judgment.

The model can add cited explanatory observations and suggested actions. Its observations carry zero policy points. Python calculates category scores, caps, risk/confidence and the recommendation. Specialist failure reduces relevant confidence and prevents GO; reviewer failure falls back to deterministic findings. The fixture source calls MCP with deterministic handoffs and is clearly labeled.

## At-least-once work

API writes create an analysis, job and outbox event in one transaction. A unique workspace/idempotency key rejects changed-body replays. Workers atomically claim due jobs with an owner token and a 120-second lease. A heartbeat renews the live lease and SQS visibility. Each checkpoint and final publication checks ownership; a worker that loses its lease cannot publish. Final report rows and completed state commit together.

Retries reuse the sealed collection and input-hashed completed agent runs. A transient dependency failure moves the job to WAITING; a permanent error or exhausted retry count produces FAILED and a durable DLQ outbox event. SQS publication can duplicate after a crash; the database claim prevents duplicate publication of the report. Reconciliation republishes due/expired jobs after lost queue messages. Default local mode polls the same job rows directly.

The synchronous `/demo/analyses` endpoint remains as a deterministic policy preview for the original learning exercises. The user-facing new-analysis screen uses the queued `/analyses` endpoint.

## Provider reliability

Redis holds short-lived namespaced results; its loss changes performance, not the saved report. An installation-wide PostgreSQL quota row serializes cache misses and persists cooldowns across API/worker processes. Each client instance deduplicates identical in-flight requests. Mutable refs/checks/reviews are freshly collected per run; immutable comparison results may be cached. Responses are bounded while streaming.

Webhook HMAC verification precedes JSON handling. Delivery IDs are unique; acknowledgement follows durable enqueue. Payload text is not retained unnecessarily. Workers invalidate caches, fetch current connection state, and mark existing reports stale without rewriting conclusions. Request timestamps prevent slower older connection refreshes from overwriting newer refreshes. Duplicate/reordered events may cause additional conservative stale annotations, never a report recalculation.

## Deliberate limits

- One owner and one repository per workspace; no organization/RBAC administration UI.
- No automatic deploy, rollback, PR comment, cloud alarm integration, shell execution or GitHub writes.
- No OCR, image-only PDFs, spreadsheets, or large repository-wide static analysis.
- Text extraction supports at most 100 PDF pages / 300,000 extracted characters / 200 chunks; uploads are limited to 5 MB.
- Demo vectors use hashed terms, not semantic embeddings. Production embeddings are 1536 dimensions.
- Review coverage and file-path complexity are heuristics; these do not prove program correctness.
- Missing policy permissions are intentionally conservative, especially for tags/SHAs that do not identify a policy branch.
- Local worker polling, mocked AWS tests and offline model fixtures are not evidence of cloud availability or real-model reliability.
- The deployment template requires existing networking, certificate, image repositories and provider secrets. It is a small single-AZ portfolio setup, not a production SLA.

## Sources

[GitHub comparison API](https://docs.github.com/en/rest/commits/commits#compare-two-commits), [GitHub App installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings), [Moto server/testing documentation](https://docs.getmoto.org/en/latest/docs/server_mode.html).
