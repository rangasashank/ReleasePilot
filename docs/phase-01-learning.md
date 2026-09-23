# Phase 1: follow one authenticated request

## What to understand

You already know full-stack development, so focus on one architectural boundary: **authentication identifies the caller; authorization decides which records they may access**.

The frontend hiding a page is a usability choice. The backend's scoped database query is the actual security boundary.

## Walk through service creation

1. `frontend/components/service-form.tsx` validates a name and description. This improves feedback but does not establish trust.
2. `frontend/app/setup/page.tsx` submits those fields with the CSRF token returned by `/me`. It sends no workspace ID.
3. `frontend/next.config.ts` forwards the same-origin request to FastAPI. The browser includes its HTTP-only cookie automatically; JavaScript cannot read it.
4. `backend/app/auth.py` hashes the opaque cookie value, loads its session, checks expiration, and resolves the workspace from its owner. A mutation also checks Origin and CSRF.
5. `backend/app/main.py` validates the body and passes the trusted workspace ID to the domain service.
6. `backend/app/services.py` commits the service. A database uniqueness constraint protects against duplicate names even when requests race.
7. The response returns the persisted record. TanStack Query invalidates the services list and the dashboard reloads it.

Read those sections in order. The important detail is where data changes from browser-supplied to trusted server context.

## Why the schema starts small

`User → Workspace → Service` is enough for this phase. Sessions reference users. A service has no repository yet because connecting GitHub is later work. Alembic records the schema change explicitly; application startup does not call `create_all`.

The one-shot Compose initializer performs migration and seed work before API startup. It is separate from the API so adding API replicas later would not make every replica run migrations.

## Three experiments (about 10 minutes)

1. **Persistence:** sign in and create `Checkout API`. Refresh, then run `docker compose restart api frontend`. The service and session remain because they live in PostgreSQL.
2. **Trust boundary:** inspect the create-service request in browser developer tools. Attempt to include a `workspace_id`: the API rejects the unknown field. Read `test_create_persist_and_scope_service` to see the stronger test: another valid account also cannot fetch the record by ID.
3. **Session revocation:** sign out. Try `/api/v1/me` again. It returns `401` because the session row was deleted. Removing a browser cookie alone would not revoke a copied token; deleting its server record does.

## Check your understanding

- Why do we validate service input in both React and FastAPI?
- Why store the session token's digest instead of the raw token?
- Why does every service query still need workspace scope after login succeeds?

Expected answers: client validation is feedback, server validation is enforcement; a database leak should not immediately expose usable session cookies; authentication alone does not authorize access to every record.

## What comes next

Phase 2 introduces normalized evidence and deterministic scoring with three fixtures. It builds on this workspace and dashboard without requiring GitHub or an LLM. Stop here first: create a service and trace the request before adding more concepts.

## Verified at this checkpoint

- Eight backend tests passed against both SQLite and PostgreSQL.
- Three frontend tests passed; lint and strict type checks passed for both applications.
- Production build and Linux Docker image builds passed with locked dependencies.
- Alembic upgrade, downgrade, and schema-drift checks passed.
- A real HTTP smoke test through Next.js verified login, CSRF, creation, and logout.
- The session and service survived a restart of PostgreSQL, FastAPI, and Next.js. The temporary smoke-test service was then removed.
- Repeating the seed preserved the existing demo account.
- GitHub Actions is configured but has not run remotely; this workspace has not been published to GitHub. Browser interactions and visual QA have not been automated in this phase.

The installed Starlette test client emits upstream deprecation warnings for its current HTTPX/AnyIO compatibility path; tests still pass.
