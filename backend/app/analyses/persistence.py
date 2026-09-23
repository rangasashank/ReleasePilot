"""Atomic publication: callers hold the job lease lock until commit."""

from sqlalchemy.orm import Session

from app.models import Analysis, ChecklistRecord, EvidenceItem, FindingCitation, FindingRecord
from app.scoring.schemas import Decision, EvidenceSnapshot


def publish(
    db: Session, analysis: Analysis, snapshot: EvidenceSnapshot, decision: Decision
) -> None:
    analysis.policy_version = decision.policy_version
    analysis.risk_score = decision.risk_score
    analysis.confidence_score = decision.confidence_score
    analysis.recommendation = decision.recommendation
    analysis.summary = decision.summary
    analysis.input_facts = snapshot.model_dump(mode="json", exclude={"evidence"})
    analysis.score_details = decision.model_dump(
        mode="json", include={"category_scores", "category_caps", "confidence_components"}
    )
    for item in snapshot.evidence:
        db.add(
            EvidenceItem(
                analysis_id=analysis.id,
                **item.model_dump(exclude={"url"}),
                url=str(item.url) if item.url else None,
            )
        )
    for index, finding in enumerate(decision.findings):
        db.add(
            FindingRecord(
                analysis_id=analysis.id,
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
            ChecklistRecord(analysis_id=analysis.id, position=index, **checklist_item.model_dump())
        )
