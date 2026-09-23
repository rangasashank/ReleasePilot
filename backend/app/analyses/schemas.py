import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from app.analyses.fixtures import Scenario
from app.scoring.schemas import Decision, Evidence, Recommendation, StrictModel


class DemoAnalysisInput(StrictModel):
    service_id: uuid.UUID
    scenario: Scenario


class ScenarioOutput(StrictModel):
    id: Scenario
    title: str
    description: str


class AnalysisSummary(StrictModel):
    state: str
    id: uuid.UUID
    service_name: str
    scenario: str
    source_mode: Literal["demo", "github"]
    recommendation: Recommendation
    risk_score: int
    confidence_score: int
    head_sha: str
    created_at: datetime


class AnalysisReport(StrictModel):
    id: uuid.UUID
    release_candidate_id: uuid.UUID
    service_name: str
    scenario: str
    source_mode: Literal["demo", "github"]
    state: Literal["COMPLETED", "PARTIAL"]
    base_sha: str
    head_sha: str
    created_at: datetime
    decision: Decision
    evidence: list[Evidence]

    @model_validator(mode="after")
    def validate_citations(self) -> Self:
        evidence_ids = {item.id for item in self.evidence}
        finding_ids = {item.id for item in self.decision.findings}
        if any(
            not set(item.evidence_ids).issubset(evidence_ids) for item in self.decision.findings
        ):
            raise ValueError("Report citations must reference its own captured evidence")
        if any(item.finding_id not in finding_ids for item in self.decision.checklist):
            raise ValueError("Checklist items must reference report findings")
        return self
