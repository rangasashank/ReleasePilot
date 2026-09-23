import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analyses.fixtures import SCENARIOS, fixture
from app.analyses.schemas import AnalysisReport, AnalysisSummary, DemoAnalysisInput
from app.models import (
    Analysis,
    ChecklistRecord,
    EvidenceItem,
    FindingCitation,
    FindingRecord,
    ReleaseCandidate,
    Service,
)
from app.scoring.engine import evaluate
from app.services import ServiceConflict, ServiceNotFound, get_service


def owned_analysis(db: Session, workspace_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis:
    analysis = db.scalar(
        select(Analysis).where(Analysis.id == analysis_id, Analysis.workspace_id == workspace_id)
    )
    if analysis is None:
        raise ServiceNotFound("Analysis not found")
    return analysis


def create_demo_analysis(
    db: Session, workspace_id: uuid.UUID, data: DemoAnalysisInput, request_key: str
) -> AnalysisReport:
    get_service(db, workspace_id, data.service_id)
    request_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()

    def existing() -> AnalysisReport | None:
        previous = db.scalar(
            select(Analysis).where(
                Analysis.workspace_id == workspace_id, Analysis.request_key == request_key
            )
        )
        if previous:
            if previous.request_hash != request_hash:
                raise ServiceConflict("Idempotency key was already used with different input")
            return get_report(db, workspace_id, previous.id)
        return None

    if report := existing():
        return report
    analysis_id = uuid.uuid4()
    # Namespace fixture IDs by analysis so repeated demos own distinct evidence records.
    snapshot = fixture(data.scenario, analysis_id)
    decision = evaluate(snapshot)
    release = ReleaseCandidate(
        workspace_id=workspace_id,
        service_id=data.service_id,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        description=SCENARIOS[data.scenario][0],
    )
    try:
        db.add(release)
        db.flush()
        analysis = Analysis(
            id=analysis_id,
            workspace_id=workspace_id,
            release_candidate_id=release.id,
            request_key=request_key,
            request_hash=request_hash,
            scenario=data.scenario,
            policy_version=decision.policy_version,
            risk_score=decision.risk_score,
            confidence_score=decision.confidence_score,
            recommendation=decision.recommendation,
            summary=decision.summary,
            input_facts=snapshot.model_dump(mode="json", exclude={"evidence"}),
            score_details=decision.model_dump(
                mode="json", include={"category_scores", "category_caps", "confidence_components"}
            ),
        )
        db.add(analysis)
        db.flush()
        for item in snapshot.evidence:
            db.add(
                EvidenceItem(
                    analysis_id=analysis_id,
                    **item.model_dump(exclude={"url"}),
                    url=str(item.url) if item.url else None,
                )
            )
        for index, finding in enumerate(decision.findings):
            db.add(
                FindingRecord(
                    analysis_id=analysis_id,
                    position=index,
                    **finding.model_dump(exclude={"evidence_ids"}),
                )
            )
        db.flush()
        for finding in decision.findings:
            for evidence_id in finding.evidence_ids:
                db.add(FindingCitation(finding_id=finding.id, evidence_item_id=evidence_id))
        for index, checklist_item in enumerate(decision.checklist):
            db.add(
                ChecklistRecord(
                    analysis_id=analysis_id, position=index, **checklist_item.model_dump()
                )
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        # A simultaneous retry can lose the unique-key race. Return the winner's complete report.
        if report := existing():
            return report
        raise
    return get_report(db, workspace_id, analysis_id)


def get_report(db: Session, workspace_id: uuid.UUID, analysis_id: uuid.UUID) -> AnalysisReport:
    analysis = owned_analysis(db, workspace_id, analysis_id)
    if analysis.state not in ("COMPLETED", "PARTIAL"):
        raise ServiceConflict("Analysis is still processing; check its status")
    release = db.get(ReleaseCandidate, analysis.release_candidate_id)
    if release is None:
        raise ServiceNotFound("Release not found")
    service = get_service(db, workspace_id, release.service_id)
    evidence = list(
        db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.analysis_id == analysis_id)
            .order_by(EvidenceItem.id)
        )
    )
    findings = list(
        db.scalars(
            select(FindingRecord)
            .where(FindingRecord.analysis_id == analysis_id)
            .order_by(FindingRecord.position)
        )
    )
    citations = db.execute(
        select(FindingCitation.finding_id, FindingCitation.evidence_item_id)
        .join(FindingRecord, FindingCitation.finding_id == FindingRecord.id)
        .where(FindingRecord.analysis_id == analysis_id)
    ).all()
    citation_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for finding_id, evidence_id in citations:
        citation_map.setdefault(finding_id, []).append(evidence_id)
    checklist = list(
        db.scalars(
            select(ChecklistRecord)
            .where(ChecklistRecord.analysis_id == analysis_id)
            .order_by(ChecklistRecord.position)
        )
    )
    decision = {
        "policy_version": analysis.policy_version,
        "risk_score": analysis.risk_score,
        "confidence_score": analysis.confidence_score,
        "recommendation": analysis.recommendation,
        "summary": analysis.summary,
        **analysis.score_details,
        "findings": [
            {
                "id": item.id,
                "rule": item.rule,
                "category": item.category,
                "kind": item.kind,
                "title": item.title,
                "explanation": item.explanation,
                "remediation": item.remediation,
                "points": item.points,
                "evidence_ids": sorted(citation_map.get(item.id, [])),
            }
            for item in findings
        ],
        "checklist": [
            {
                "id": item.id,
                "finding_id": item.finding_id,
                "title": item.title,
                "required": item.required,
                "status": item.status,
            }
            for item in checklist
        ],
    }
    return AnalysisReport.model_validate(
        {
            "id": analysis.id,
            "release_candidate_id": release.id,
            "service_name": service.name,
            "scenario": analysis.scenario,
            "source_mode": analysis.source_mode,
            "state": analysis.state,
            "base_sha": release.base_sha,
            "head_sha": release.head_sha,
            "created_at": analysis.created_at,
            "decision": decision,
            "evidence": [
                {
                    "id": item.id,
                    "source_type": item.source_type,
                    "title": item.title,
                    "excerpt": item.excerpt,
                    "locator": item.locator,
                    "url": item.url,
                    "captured_at": item.captured_at,
                }
                for item in evidence
            ],
        }
    )


def recent_analyses(
    db: Session, workspace_id: uuid.UUID, limit: int, offset: int
) -> list[AnalysisSummary]:
    rows = db.execute(
        select(Analysis, ReleaseCandidate, Service)
        .join(ReleaseCandidate, Analysis.release_candidate_id == ReleaseCandidate.id)
        .join(Service, ReleaseCandidate.service_id == Service.id)
        .where(
            Analysis.workspace_id == workspace_id,
            Service.workspace_id == workspace_id,
        )
        .order_by(Analysis.created_at.desc(), Analysis.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        AnalysisSummary.model_validate(
            {
                "id": analysis.id,
                "service_name": service.name,
                "scenario": analysis.scenario,
                "source_mode": analysis.source_mode,
                "state": analysis.state,
                "recommendation": analysis.recommendation,
                "risk_score": analysis.risk_score,
                "confidence_score": analysis.confidence_score,
                "head_sha": release.head_sha,
                "created_at": analysis.created_at,
            }
        )
        for analysis, release, service in rows
    ]
