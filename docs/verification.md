# Verification record

Verified locally on September 10, 2026. These results describe the checked-in implementation and a local Docker environment; they do not establish production performance or live-model quality.

| Check | Observed result |
| --- | --- |
| Backend PostgreSQL suite | 71 passed, including concurrent submission idempotency, workspace isolation, lease fencing, retries, citation validation, and provider failure handling |
| Backend static checks | Ruff lint/format and mypy passed |
| Database migrations | Upgrade, downgrade, fresh upgrade, and Alembic metadata drift checks passed against a disposable PostgreSQL database |
| Frontend | Lint, TypeScript, 7 tests, and production Docker build passed |
| Offline policy/security evaluation | 18/18 cases passed; zero false GO results for required-check failures; two unauthorized tool requests blocked |
| Retrieval fixtures | Six golden queries passed recall@5 with demo vectors; no cross-workspace results |
| AWS adapters | S3/SQS behavior covered with Moto; CloudFormation template passed cfn-lint |
| Full-stack HTTP smoke | Three queued scenarios completed through the frontend, API, worker, PostgreSQL, and private HTTP MCP server |
| Document workflow | Upload, background indexing, and passage retrieval passed using `demo-hash-v1` |
| Browser | Sign-in, report creation, exact-check citation, Escape dismissal and focus return, knowledge search, connections page, and desktop/mobile layout checked |

The final smoke run produced GO for the safe fixture, NO_GO for failed required CI, and CAUTION for missing evidence. Each completed three deterministic agent runs and three real HTTP MCP calls. Observed completion times were 1.06, 1.06, and 1.03 seconds, respectively. These are local synthetic timings, not live-provider or production latency measurements. The smoke script records local run IDs and timings in ignored `artifacts/smoke.json`.

The [offline evaluation output](../evals/results.json) is reproducible with the commands in the [README](../README.md#development-and-verification). Its policy timings measure the policy function only. Fixture retrieval recall is not a claim about semantic relevance with real embeddings. Tests emitted two dependency deprecation warnings from Starlette/AnyIO; no failures remained.

## Remaining environment-dependent verification

- GitHub App installation/OAuth and authenticated analysis against a real repository require your credentials and callback configuration. Provider behavior is covered with controlled responses locally.
- OpenAI generation and embeddings require your API key. Live model quality, latency, and spending have not been measured. Demo analysis stays deterministic even when a key is configured.
- AWS resources have not been deployed. The ECS/RDS/S3/SQS template and deployment instructions are prepared; cloud networking, IAM, migrations, and recovery need verification in your account.
- The default local worker polls PostgreSQL. SQS adapter tests use Moto; no LocalStack environment was used.
- Citation checks establish captured-source membership and exact quoted text, not semantic entailment. Risk/confidence scores are versioned heuristics, not calibrated probabilities.

No repository has been pushed and no cloud resources have been created by this work.

## Browser captures

The screenshots show a synthetic failed-CI report in the local application.

![Desktop report](images/report.png)

[Mobile report capture](images/report-mobile.png)
