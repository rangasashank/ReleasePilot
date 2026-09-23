# Learn the finished implementation in small sessions

Use one session per row. Start by running the example, then trace the named files. Change one behavior and predict the result before running the tests.

| Session | Read | Exercise / checkpoint |
|---|---|---|
| 1. Requests and validation | `backend/app/main.py`, `schemas.py`, `auth.py` | Trace login → cookie → `/me`. Compare Pydantic input validation with Joi. |
| 2. Relational persistence | `models.py`, `db.py`, `migrations/` | Draw workspace → service → release → analysis → evidence/findings. Explain foreign keys versus embedding a MongoDB document. |
| 3. Pure business rules | `scoring/schemas.py`, `scoring/engine.py` | Turn one required check from success to failure. Explain why a low-confidence report can never be GO. |
| 4. API contracts and UI | `frontend/lib/api.ts`, `app/analyses/`, `components/reports/` | Trace generated OpenAPI types into a report. Inspect loading, failed and partial states. |
| 5. GitHub collection | `github/client.py`, `github/collector.py` | Trace a full SHA, required App-bound check, and incomplete pagination. Explain why an optional passing check cannot replace a required failed one. |
| 6. Retrieval | `documents/retrieval.py`, `documents/router.py` | Upload two runbooks, search a phrase, and inspect headings. Explain vectors, lexical ranking, RRF, and why filtering happens before ranking. |
| 7. Durable jobs | `jobs/state.py`, `jobs/worker.py`, `jobs/pipeline.py` | Read the stale-worker test. Draw what happens when a process crashes after saving a checkpoint. |
| 8. Outbox and providers | `jobs/queue.py`, `webhooks/router.py` | Explain the gap between committing a DB transaction and publishing a message, then how the outbox closes it. |
| 9. MCP | `mcp_tools/server.py`, `client.py` | Trace a knowledge-agent token and scoped search call. Attempt an unauthorized tool in the test suite. |
| 10. Bounded agents | `agents/runner.py`, `schemas.py` | Trace fan-out/fan-in, structured handoffs, budgets, citation rejection and deterministic fallback. |
| 11. Evaluation | `backend/evals/run.py`, `backend/tests/` | Add a scenario before changing a policy rule. Distinguish policy gates from model-quality measurements. |
| 12. Deployment | Dockerfiles, Compose, `infrastructure/aws/` | Explain which state survives container replacement. Read the cost/teardown guide before creating cloud resources. |

Pydantic **schemas** describe and validate data at boundaries (requests, evidence, agent outputs and responses). SQLAlchemy **models** describe persisted tables and relationships. Migrations change the actual database schema. Unlike a typical Mongoose schema that can combine storage mapping and validation in one object, those responsibilities are deliberately separated here.

Keep the earlier phase 1/2 walkthroughs as a slower introduction. They describe the starting implementation; this table is the route through the completed local workflow.
