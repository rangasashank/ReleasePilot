import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.runner import analyze
from app.analyses.fixtures import fixture
from app.analyses.persistence import publish
from app.db import get_engine
from app.documents.retrieval import chunk_pages, embed, extract, search
from app.documents.storage import get_object
from app.errors import IntegrationError
from app.github.client import GitHubClient
from app.github.collector import collect
from app.jobs.state import checkpoint, locked_job
from app.models import Analysis, Document, DocumentChunk, ReleaseCandidate, Repository
from app.scoring.engine import evaluate
from app.scoring.schemas import ChecklistItem, Evidence, EvidenceSnapshot, Finding


def index_document(job_id: uuid.UUID, owner: str) -> None:
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        doc = db.get(Document, uuid.UUID(str(job.payload["document_id"])))
        assert doc and doc.workspace_id == job.workspace_id
        key, extension, model = doc.object_key, doc.media_type, doc.embedding_model
        db.commit()
    chunks = chunk_pages(extract(get_object(key), extension))
    vectors = []
    for start in range(0, len(chunks), 20):
        vectors.extend(embed([c["content"] for c in chunks[start : start + 20]], model))
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        doc = db.get(Document, uuid.UUID(str(job.payload["document_id"])))
        assert doc
        if not doc.deleted:
            for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                db.add(DocumentChunk(document_id=doc.id, position=i, embedding=vector, **chunk))
            doc.status, doc.error_code = "READY", None
            if job.payload.get("replaces"):
                previous = db.get(Document, uuid.UUID(str(job.payload["replaces"])))
                if previous and previous.workspace_id == doc.workspace_id:
                    previous.deleted = True
        job.state, job.stage, job.lease_owner, job.lease_expires_at = (
            "COMPLETED",
            "INDEXED",
            None,
            None,
        )
        db.commit()


def run_analysis(job_id: uuid.UUID, owner: str) -> None:
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        analysis = db.get(Analysis, job.analysis_id)
        assert analysis
        release = db.get(ReleaseCandidate, analysis.release_candidate_id)
        assert release
        analysis.state = "RUNNING"
        analysis_id, source, scenario = analysis.id, analysis.source_mode, analysis.scenario
        saved = job.checkpoints.get("snapshot")
        if not saved:
            job.stage = "COLLECTING"
            if source == "demo":
                snapshot = fixture(scenario, analysis_id)  # type: ignore[arg-type]
            else:
                repo = db.get(Repository, release.repository_id)
                if not repo or repo.status != "connected":
                    raise IntegrationError("GITHUB_DISCONNECTED", "Reconnect the repository")
                db.commit()  # Do not hold the lease lock during provider requests.
                client = GitHubClient(repo)
                try:
                    snapshot = collect(
                        client, release.base_sha, release.head_sha, analysis_id, release.head_ref
                    )
                finally:
                    client.close()
            checkpoint(db, job_id, owner, "snapshot", snapshot.model_dump(mode="json"))
        else:
            snapshot = EvidenceSnapshot.model_validate(saved)
        job = locked_job(db, job_id, owner)
        knowledge = job.checkpoints.get("knowledge")
        db.commit()
        if knowledge:
            snapshot = EvidenceSnapshot.model_validate(knowledge)
        elif source != "demo":
            chunks = search(
                db,
                analysis.workspace_id,
                release.service_id,
                "deployment migration rollback " + " ".join(snapshot.changes.paths)[:1000],
            )
            ids = []
            migration, rollback = [], []
            for chunk in chunks:
                eid = uuid.uuid5(analysis_id, chunk["chunk_id"])
                ids.append(eid)
                snapshot.evidence.append(
                    Evidence(
                        id=eid,
                        source_type="runbook",
                        title=chunk["title"],
                        excerpt=chunk["excerpt"],
                        locator=f"document:{chunk['document_id']}/chunk:{chunk['chunk_id']}",
                        captured_at=datetime.now(UTC),
                    )
                )
                # Conservative lexical heuristics; these are not AI-derived facts.
                text = chunk["excerpt"].lower()
                if (
                    "migration" in text
                    and re.search(r"backup|back up|snapshot", text)
                    and not re.search(r"no backup|without backup|backup.*missing", text)
                ):
                    migration.append(eid)
                if (
                    re.search(r"rollback|roll back", text)
                    and re.search(r"restore|revert|previous image", text)
                    and not re.search(r"no rollback|cannot roll|rollback.*unavailable", text)
                ):
                    rollback.append(eid)
            collection = next(
                e for e in snapshot.evidence if e.id == snapshot.documents.evidence_id
            )
            collection.excerpt = (
                f"Retrieved {len(ids)} relevant service runbook passages. "
                "Guidance detection uses conservative text heuristics."
            )
            collection.captured_at = datetime.now(UTC)
            snapshot.documents = snapshot.documents.model_copy(
                update={
                    "indexed": bool(ids),
                    "availability": "complete" if ids else "missing",
                    "retrieved_ids": ids,
                    "migration_guidance_ids": migration,
                    "rollback_ids": rollback,
                }
            )
            checkpoint(db, job_id, owner, "knowledge", snapshot.model_dump(mode="json"))
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        job.stage = "SPECIALISTS"
        db.commit()
    outputs = analyze(analysis_id, owner, snapshot)
    decision = evaluate(snapshot)
    partial = any(o["status"] == "partial" for o in outputs)
    old_confidence = decision.confidence_score
    for role_index, categories in ((0, {"changes", "reviews", "ci"}), (1, {"runbooks"})):
        if len(outputs) > role_index and outputs[role_index]["status"] == "partial":
            for component in decision.confidence_components:
                if component.category in categories:
                    component.earned //= 2
                    component.reason += " Specialist reasoning incomplete; confidence reduced."
    decision.confidence_score = sum(c.earned for c in decision.confidence_components)
    decision.summary = decision.summary.replace(
        f"confidence is {old_confidence}/100", f"confidence is {decision.confidence_score}/100"
    )
    # Specialists add explanatory observations only. Policy owns every score and blocker.
    reviewer: dict[str, Any] = outputs[-1]
    for i, finding in enumerate(reviewer["findings"]):
        fid = uuid.uuid5(analysis_id, f"reviewer:{i}")
        decision.findings.append(
            Finding(
                id=fid,
                rule=f"ai.observation.{i}",
                category=finding["category"],
                kind="warning",
                title=finding["title"],
                explanation=finding["explanation"],
                remediation=finding["remediation"],
                points=0,
                evidence_ids=[uuid.UUID(eid) for eid in finding["evidence_ids"]],
            )
        )
        if finding["remediation"]:
            decision.checklist.append(
                ChecklistItem(
                    id=uuid.uuid5(fid, "checklist"),
                    finding_id=fid,
                    title=finding["remediation"],
                    required=False,
                )
            )
    if partial and decision.recommendation == "GO":
        decision.recommendation = "CAUTION"
        decision.summary = (
            "Policy checks passed, but specialist review is incomplete. Review before releasing."
        )
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        analysis = db.get(Analysis, analysis_id)
        assert analysis
        publish(db, analysis, snapshot, decision)
        analysis.state = "PARTIAL" if partial else "COMPLETED"
        job.state, job.stage, job.lease_owner, job.lease_expires_at = (
            "COMPLETED",
            "COMPLETED",
            None,
            None,
        )
        db.commit()
