import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analyses.fixtures import fixture
from app.analyses.service import owned_analysis
from app.auth import Identity, current_identity, mutation_identity
from app.db import get_db
from app.github.client import GitHubClient
from app.github.router import owned_repository
from app.jobs.state import enqueue
from app.models import AgentRun, Analysis, Job, OutboxEvent, ReleaseCandidate, ToolCall
from app.scoring.schemas import StrictModel
from app.services import get_service

router = APIRouter(prefix="/api/v1", tags=["jobs"])


class StartInput(StrictModel):
    service_id: uuid.UUID
    mode: Literal["demo", "github"] = "demo"
    scenario: Literal["safe", "failed_ci", "missing_evidence"] = "failed_ci"
    base_ref: str = Field(default="", max_length=200)
    head_ref: str = Field(default="", max_length=200)


@router.post("/analyses", status_code=202)
def start(
    data: StartInput,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
    idempotency_key: str = Header(min_length=8, max_length=128),
) -> dict[str, Any]:
    get_service(db, identity.workspace.id, data.service_id)
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    previous = db.scalar(
        select(Analysis).where(
            Analysis.workspace_id == identity.workspace.id, Analysis.request_key == idempotency_key
        )
    )
    if previous:
        if previous.request_hash != digest:
            raise HTTPException(409, "Idempotency key was used for different input")
        return {"id": str(previous.id), "state": previous.state}
    analysis_id = uuid.uuid4()
    repository_id = None
    if data.mode == "demo":
        snapshot = fixture(data.scenario, analysis_id)
        base, head = snapshot.base_sha, snapshot.head_sha
    else:
        repo = owned_repository(db, identity.workspace.id)
        if repo.status != "connected":
            raise HTTPException(409, "Reconnect GitHub before analyzing")
        if not data.base_ref.strip() or not data.head_ref.strip():
            raise HTTPException(422, "Select both release references")
        client = GitHubClient(repo)
        try:
            base, head = client.resolve(data.base_ref), client.resolve(data.head_ref)
        finally:
            client.close()
        repository_id = repo.id
        if base == head:
            raise HTTPException(422, "Base and target resolve to the same commit")
    release = ReleaseCandidate(
        workspace_id=identity.workspace.id,
        service_id=data.service_id,
        repository_id=repository_id,
        base_ref=data.base_ref or None,
        head_ref=data.head_ref or None,
        base_sha=base,
        head_sha=head,
        description="Release readiness analysis",
    )
    try:
        db.add(release)
        db.flush()
        analysis = Analysis(
            id=analysis_id,
            workspace_id=identity.workspace.id,
            release_candidate_id=release.id,
            request_key=idempotency_key,
            request_hash=digest,
            scenario=data.scenario if data.mode == "demo" else "live",
            source_mode=data.mode,
            state="QUEUED",
            policy_version="readiness-v1",
            risk_score=0,
            confidence_score=0,
            recommendation="CAUTION",
            summary="Analysis queued",
            input_facts={},
            score_details={},
        )
        db.add(analysis)
        db.flush()
        enqueue(db, identity.workspace.id, "analysis", f"analysis:{analysis_id}", {}, analysis_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(Analysis).where(
                Analysis.workspace_id == identity.workspace.id,
                Analysis.request_key == idempotency_key,
            )
        )
        if not winner or winner.request_hash != digest:
            raise HTTPException(409, "Concurrent request conflict") from None
        return {"id": str(winner.id), "state": winner.state}
    return {"id": str(analysis.id), "state": analysis.state}


@router.get("/analyses/{analysis_id}/status")
def status(
    analysis_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    analysis = owned_analysis(db, identity.workspace.id, analysis_id)
    job = db.scalar(select(Job).where(Job.analysis_id == analysis_id))
    agents = db.scalars(select(AgentRun).where(AgentRun.analysis_id == analysis_id)).all()
    calls = db.scalars(select(ToolCall).where(ToolCall.analysis_id == analysis_id)).all()
    return {
        "id": str(analysis_id),
        "state": analysis.state,
        "stale": analysis.stale,
        "stage": job.stage if job else "COMPLETED",
        "attempts": job.attempts if job else 0,
        "error_code": job.last_error_code if job else None,
        "retry_at": job.next_attempt_at.isoformat() if job and job.state == "WAITING" else None,
        "agents": [
            {
                "name": a.agent_type,
                "state": a.state,
                "model": a.model_name,
                "tokens": a.token_count,
                "duration_ms": a.duration_ms,
                "output": a.output,
            }
            for a in agents
        ],
        "tools": [
            {
                "name": c.name,
                "agent": c.agent_type,
                "status": c.status,
                "duration_ms": c.duration_ms,
            }
            for c in calls
        ],
    }


@router.post("/analyses/{analysis_id}/retry", status_code=202)
def retry(
    analysis_id: uuid.UUID,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    owned_analysis(db, identity.workspace.id, analysis_id)
    job = db.scalar(select(Job).where(Job.analysis_id == analysis_id).with_for_update())
    if not job or job.state != "FAILED":
        raise HTTPException(409, "Only failed jobs can be retried")
    job.state, job.attempts, job.last_error_code = "READY", 0, None
    job.next_attempt_at = datetime.now(UTC)
    analysis = db.get(Analysis, analysis_id)
    assert analysis
    analysis.state = "QUEUED"
    db.add(OutboxEvent(job_id=job.id))
    db.commit()
    return {"state": "QUEUED"}
