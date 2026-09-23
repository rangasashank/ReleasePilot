import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.runner import validate_handoff
from app.agents.schemas import AgentHandoff
from app.analyses.fixtures import fixture
from app.config import get_settings
from app.documents.retrieval import chunk_pages, extract
from app.errors import IntegrationError, LeaseLost
from app.jobs.pipeline import index_document, run_analysis
from app.jobs.state import checkpoint, claim, locked_job
from app.models import (
    Analysis,
    Job,
    OutboxEvent,
    Repository,
    WebhookDelivery,
)
from tests.conftest import sign_in
from tests.test_analyses import setup_service


def test_enqueue_replay_and_status_scope(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    body = {"service_id": service_id, "mode": "demo", "scenario": "failed_ci"}
    first = client.post("/api/v1/analyses", json=body, headers=headers)
    assert first.status_code == 202, first.text
    second = client.post("/api/v1/analyses", json=body, headers=headers)
    assert first.json() == second.json()
    assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    aid = first.json()["id"]
    assert client.get(f"/api/v1/analyses/{aid}").status_code == 409
    assert client.get(f"/api/v1/analyses/{aid}/status").json()["state"] == "QUEUED"
    assert (
        client.post(
            "/api/v1/analyses", json={**body, "scenario": "safe"}, headers=headers
        ).status_code
        == 409
    )
    sign_in(client, 2)
    assert client.get(f"/api/v1/analyses/{aid}/status").status_code == 404


def test_lease_reclaim_fences_stale_worker(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    client.post("/api/v1/analyses", json={"service_id": service_id}, headers=headers)
    job = db.scalar(select(Job))
    assert job
    first = claim(db, job.id)
    assert first and claim(db, job.id) is None
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    second = claim(db, job.id)
    assert second and second != first
    with pytest.raises(LeaseLost):
        locked_job(db, job.id, first)
    checkpoint(db, job.id, second, "test", {"saved": True})
    assert job.checkpoints["test"] == {"saved": True}


def test_publication_and_duplicate_delivery(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    created = client.post(
        "/api/v1/analyses",
        json={"service_id": service_id, "scenario": "failed_ci"},
        headers=headers,
    )
    job = db.scalar(select(Job))
    assert job
    owner = claim(db, job.id)
    assert owner
    result = [{"status": "completed", "findings": []}] * 3
    with (
        patch("app.jobs.pipeline.get_engine", return_value=db.get_bind()),
        patch("app.jobs.pipeline.analyze", return_value=result),
    ):
        run_analysis(job.id, owner)
    db.expire_all()
    report = client.get(f"/api/v1/analyses/{created.json()['id']}")
    assert report.status_code == 200, report.text
    assert report.json()["decision"]["recommendation"] == "NO_GO"
    assert claim(db, job.id) is None
    assert db.scalar(select(func.count()).select_from(Analysis)) == 1


def test_partial_agent_cannot_clear_blocker(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    created = client.post(
        "/api/v1/analyses",
        json={"service_id": service_id, "scenario": "failed_ci"},
        headers=headers,
    )
    job = db.scalar(select(Job))
    assert job
    owner = claim(db, job.id)
    assert owner
    with (
        patch("app.jobs.pipeline.get_engine", return_value=db.get_bind()),
        patch("app.jobs.pipeline.analyze", return_value=[{"status": "partial", "findings": []}]),
    ):
        run_analysis(job.id, owner)
    db.expire_all()
    report = client.get(f"/api/v1/analyses/{created.json()['id']}").json()
    assert report["state"] == "PARTIAL"
    assert report["decision"]["recommendation"] == "NO_GO"


def test_citation_validator_rejects_foreign_ids_and_fabricated_quotes() -> None:
    snapshot = fixture("safe")
    item = snapshot.evidence[0]
    base = {
        "category": "complexity",
        "title": "Observation",
        "explanation": "Change observed",
        "remediation": "Review",
        "evidence_ids": [str(item.id)],
        "quotes": [item.excerpt[:30]],
    }
    handoff = AgentHandoff.model_validate(
        {
            "agent": "reviewer",
            "status": "completed",
            "summary": "Checked",
            "components": [],
            "findings": [
                base,
                {**base, "quotes": ["fabricated"]},
                {**base, "evidence_ids": [str(uuid.uuid4())]},
            ],
            "missing_evidence": [],
            "contradictions": [],
        }
    )
    accepted = validate_handoff(handoff, snapshot)
    assert len(accepted.findings) == 1
    assert accepted.status == "partial"


def test_document_extract_bounds_and_chunks() -> None:
    chunks = chunk_pages(
        extract(
            b"# Rollback\nRestore the previous image.\n# Migration\nBack up the database.", ".md"
        )
    )
    assert [c["heading"] for c in chunks] == ["Rollback", "Migration"]
    with pytest.raises(IntegrationError, match="No text"):
        extract(b"  ", ".txt")
    with pytest.raises(IntegrationError, match="not a PDF"):
        extract(b"not a pdf", ".pdf")
    with pytest.raises(IntegrationError, match="UTF-8"):
        extract(b"\xff", ".txt")


def test_upload_index_search_delete_scope(
    client: TestClient, db: Session, tmp_path: object
) -> None:
    headers, sid = setup_service(client)
    settings = get_settings()
    with (
        patch.object(settings, "local_object_dir", str(tmp_path)),
        patch("app.jobs.pipeline.get_engine", return_value=db.get_bind()),
    ):
        response = client.post(
            "/api/v1/documents",
            data={"service_id": sid},
            files={
                "file": (
                    "rollback.md",
                    b"# Rollback\nRollback checkout by restoring the previous image.",
                )
            },
            headers=headers,
        )
        assert response.status_code == 202, response.text
        job = db.scalar(select(Job).where(Job.kind == "index"))
        assert job
        owner = claim(db, job.id)
        assert owner
        index_document(job.id, owner)
        db.expire_all()
        chunks = client.get(f"/api/v1/documents/search?service_id={sid}&query=rollback").json()
        assert len(chunks) == 1
        assert chunks[0]["heading"] == "Rollback"
        assert (
            client.get(f"/api/v1/documents/search?service_id={sid}&query=astronaut%20nebula").json()
            == []
        )
        docid = response.json()["id"]
        other_headers = sign_in(client, 2)
        assert client.delete(f"/api/v1/documents/{docid}", headers=other_headers).status_code == 404
        headers = sign_in(client)
        assert client.delete(f"/api/v1/documents/{docid}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/documents/search?service_id={sid}&query=rollback").json() == []


def test_signed_webhook_deduplicates_durable_work(client: TestClient, db: Session) -> None:
    _, sid = setup_service(client)
    from app.models import Service

    service = db.get(Service, uuid.UUID(sid))
    assert service
    db.add(
        Repository(
            workspace_id=service.workspace_id,
            github_id=123,
            full_name="owner/repo",
            default_branch="main",
            auth_mode="public",
        )
    )
    db.commit()
    body = json.dumps({"repository": {"id": 123}}).encode()
    secret = "test-webhook-secret"
    from pydantic import SecretStr

    with patch.object(get_settings(), "github_webhook_secret", SecretStr(secret)):
        headers = {
            "x-github-delivery": "delivery-123",
            "x-github-event": "push",
            "x-hub-signature-256": "sha256="
            + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
        }
        assert (
            client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={**headers, "x-hub-signature-256": "bad"},
            ).status_code
            == 401
        )
        assert db.scalar(select(func.count()).select_from(WebhookDelivery)) == 0
        for _ in range(2):
            assert (
                client.post("/api/v1/webhooks/github", content=body, headers=headers).status_code
                == 202
            )
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_transient_worker_failure_requeues_and_exhaustion_is_terminal(
    client: TestClient, db: Session
) -> None:
    from app.jobs.worker import process

    headers, sid = setup_service(client)
    client.post("/api/v1/analyses", json={"service_id": sid}, headers=headers)
    job = db.scalar(select(Job))
    assert job
    with (
        patch("app.jobs.worker.get_engine", return_value=db.get_bind()),
        patch(
            "app.jobs.worker.run_analysis",
            side_effect=IntegrationError("GITHUB_RATE_LIMIT", "Wait", 30),
        ),
    ):
        assert process(job.id)
        db.expire_all()
        assert job.state == "WAITING"
        assert job.last_error_code == "GITHUB_RATE_LIMIT"
        assert job.lease_owner is None
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2
        job.attempts = get_settings().max_job_attempts - 1
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert process(job.id)
        db.expire_all()
        assert job.state == "FAILED"
        analysis = db.get(Analysis, job.analysis_id)
        assert analysis and analysis.state == "FAILED"
        assert (
            client.post(f"/api/v1/analyses/{analysis.id}/retry", headers=headers).status_code == 202
        )
        db.expire_all()
        assert job.state == "READY" and job.attempts == 0


def test_mcp_workspace_and_global_budget(client: TestClient, db: Session) -> None:
    from app.mcp_tools.server import execute
    from app.models import ToolCall

    headers, sid = setup_service(client)
    created = client.post("/api/v1/analyses", json={"service_id": sid}, headers=headers).json()
    analysis = db.get(Analysis, uuid.UUID(created["id"]))
    job = db.scalar(select(Job))
    assert job and analysis
    owner = claim(db, job.id)
    claims = {
        "agent": "change_ci",
        "analysis_id": str(analysis.id),
        "workspace_id": str(uuid.uuid4()),
        "lease_owner": owner,
    }
    with patch("app.mcp_tools.server.get_engine", return_value=db.get_bind()):
        with pytest.raises(ValueError, match="no longer active"):
            execute("compare_commits", {}, claims)
        claims["workspace_id"] = str(analysis.workspace_id)
        for index in range(10):
            db.add(
                ToolCall(
                    analysis_id=analysis.id,
                    agent_type="knowledge",
                    name="search_runbooks",
                    input_hash=str(index),
                    status="COMPLETED",
                )
            )
        db.commit()
        with pytest.raises(ValueError, match="budget exhausted"):
            execute("compare_commits", {}, claims)


def test_golden_retrieval_recall_and_workspace_isolation(client: TestClient, db: Session) -> None:
    from app.documents.retrieval import DEMO_EMBEDDING, embed, search
    from app.models import Document, DocumentChunk, Service

    _, sid = setup_service(client)
    service = db.get(Service, uuid.UUID(sid))
    assert service
    topics = [
        "rollback previous image",
        "migration database backup",
        "authentication token rotation",
        "feature flags rollout",
        "queue dead letter recovery",
        "cache eviction refresh",
    ]
    expected = []
    for topic in topics:
        doc = Document(
            workspace_id=service.workspace_id,
            service_id=service.id,
            title=topic,
            media_type=".md",
            object_key=str(uuid.uuid4()),
            content_hash=str(uuid.uuid4()),
            status="READY",
            embedding_model=DEMO_EMBEDDING,
        )
        db.add(doc)
        db.flush()
        chunk = DocumentChunk(
            document_id=doc.id,
            position=0,
            content=topic,
            heading=topic,
            embedding=embed([topic], DEMO_EMBEDDING)[0],
        )
        db.add(chunk)
        db.flush()
        expected.append(str(chunk.id))
    db.commit()
    hits = 0
    for topic, target in zip(topics, expected, strict=True):
        results = search(db, service.workspace_id, service.id, topic)
        hits += target in {r["chunk_id"] for r in results}
        assert search(db, uuid.uuid4(), service.id, topic) == []
    assert hits / len(topics) == 1.0  # Six tiny lexical cases; not a semantic-model quality claim.


def test_completed_agent_resume_does_not_repeat_tools(client: TestClient, db: Session) -> None:
    from unittest.mock import AsyncMock

    from app.agents.runner import run_agent
    from app.models import AgentRun

    headers, sid = setup_service(client)
    created = client.post("/api/v1/analyses", json={"service_id": sid}, headers=headers).json()
    job = db.scalar(select(Job))
    assert job
    owner = claim(db, job.id)
    assert owner
    aid = uuid.UUID(created["id"])
    snapshot = fixture("failed_ci", aid)
    with (
        patch("app.agents.runner.get_engine", return_value=db.get_bind()),
        patch("app.agents.runner.discover", new=AsyncMock(return_value=[])),
        patch("app.agents.runner.call_tool", return_value={}) as tools,
    ):
        first = run_agent(aid, owner, "change_ci", snapshot, [])
        second = run_agent(aid, owner, "change_ci", snapshot, [])
        assert first == second
        assert tools.call_count == 2
    db.expire_all()
    run = db.scalar(select(AgentRun))
    assert run and run.attempts == 1 and run.state == "COMPLETED"


def test_demo_mcp_never_calls_live_retrieval(client: TestClient, db: Session) -> None:
    from app.mcp_tools.server import execute

    headers, sid = setup_service(client)
    created = client.post("/api/v1/analyses", json={"service_id": sid}, headers=headers).json()
    analysis = db.get(Analysis, uuid.UUID(created["id"]))
    job = db.scalar(select(Job))
    assert job and analysis
    owner = claim(db, job.id)
    assert owner
    checkpoint(db, job.id, owner, "snapshot", fixture("safe", analysis.id).model_dump(mode="json"))
    claims = {
        "agent": "knowledge",
        "analysis_id": str(analysis.id),
        "workspace_id": str(analysis.workspace_id),
        "lease_owner": owner,
    }
    with (
        patch("app.mcp_tools.server.get_engine", return_value=db.get_bind()),
        patch(
            "app.mcp_tools.server.search",
            side_effect=AssertionError("Must not call live embedding provider"),
        ),
    ):
        result = execute(
            "search_runbooks", {"service_id": sid, "query": "rollback", "top_k": 5}, claims
        )
        assert result["chunks"] and result["chunks"][0]["embedding_model"] == "fixture"


def test_concurrent_submission_has_one_logical_result(client: TestClient, db: Session) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from typing import Any, cast

    from app.jobs.router import StartInput, start
    from app.models import ReleaseCandidate, Service

    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Concurrent transactions require PostgreSQL")
    _, sid = setup_service(client)
    service = db.get(Service, uuid.UUID(sid))
    assert service
    workspace_id = service.workspace_id
    barrier = Barrier(2)

    def submit() -> dict[str, object]:
        with Session(db.get_bind()) as isolated:
            barrier.wait(timeout=5)
            return start(
                StartInput(service_id=uuid.UUID(sid)),
                identity=cast(Any, SimpleNamespace(workspace=SimpleNamespace(id=workspace_id))),
                db=isolated,
                idempotency_key="concurrent-analysis",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [f.result() for f in [pool.submit(submit), pool.submit(submit)]]
    assert first["id"] == second["id"]
    for model in (Analysis, Job, OutboxEvent, ReleaseCandidate):
        assert db.scalar(select(func.count()).select_from(model)) == 1
