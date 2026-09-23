import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Category = Literal["tests", "code_review", "complexity", "documentation"]
Conclusion = Literal[
    "success", "failure", "cancelled", "skipped", "neutral", "pending", "missing", "timed_out"
]
Availability = Literal["complete", "partial", "missing"]
Recommendation = Literal["GO", "CAUTION", "NO_GO"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    id: uuid.UUID
    source_type: Literal["comparison", "review", "check", "runbook", "collection"]
    title: str
    excerpt: str
    locator: str
    url: HttpUrl | None = None
    captured_at: datetime


class Check(StrictModel):
    evidence_id: uuid.UUID
    name: str = Field(min_length=1)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    conclusion: Conclusion
    attempt: int = Field(default=1, ge=1)


class Review(StrictModel):
    evidence_id: uuid.UUID
    state: Literal["approved", "unapproved", "changes_requested"]


class ChangeData(StrictModel):
    evidence_id: uuid.UUID
    availability: Availability
    paths: list[str]
    changed_lines: int = Field(ge=0)
    direct_commits: int = Field(default=0, ge=0)


class ReviewData(StrictModel):
    evidence_id: uuid.UUID
    availability: Availability
    reviews: list[Review]


class CIData(StrictModel):
    evidence_id: uuid.UUID
    availability: Availability
    policy_known: bool
    required_checks: list[str]
    checks: list[Check]

    @model_validator(mode="after")
    def unique_attempts(self) -> Self:
        keys = [(check.name, check.head_sha, check.attempt) for check in self.checks]
        if len(keys) != len(set(keys)):
            raise ValueError("Check name, SHA, and attempt must be unique")
        if len(self.required_checks) != len(set(self.required_checks)):
            raise ValueError("Required check names must be unique")
        return self


class DocumentData(StrictModel):
    evidence_id: uuid.UUID
    availability: Availability
    indexed: bool
    retrieved_ids: list[uuid.UUID]
    migration_guidance_ids: list[uuid.UUID] = Field(default_factory=list)
    rollback_ids: list[uuid.UUID] = Field(default_factory=list)


class EvidenceSnapshot(StrictModel):
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    evidence: list[Evidence]
    changes: ChangeData
    reviews: ReviewData
    ci: CIData
    documents: DocumentData

    @model_validator(mode="after")
    def validate_evidence_graph(self) -> Self:
        if self.base_sha == self.head_sha:
            raise ValueError("Base and target SHA must differ")
        owned = {item.id: item for item in self.evidence}
        if len(owned) != len(self.evidence):
            raise ValueError("Duplicate evidence IDs")
        references = [
            self.changes.evidence_id,
            self.reviews.evidence_id,
            self.ci.evidence_id,
            self.documents.evidence_id,
            *(check.evidence_id for check in self.ci.checks),
            *(review.evidence_id for review in self.reviews.reviews),
            *self.documents.retrieved_ids,
        ]
        if not set(references).issubset(owned):
            raise ValueError("Every evidence reference must belong to this snapshot")
        for check in self.ci.checks:
            if owned[check.evidence_id].source_type != "check":
                raise ValueError("Check facts require check evidence")
        for review in self.reviews.reviews:
            if owned[review.evidence_id].source_type != "review":
                raise ValueError("Review facts require review evidence")
        docs = self.documents
        if not set(docs.migration_guidance_ids + docs.rollback_ids).issubset(docs.retrieved_ids):
            raise ValueError("Guidance must be among retrieved document evidence")
        if any(owned[item].source_type != "runbook" for item in docs.retrieved_ids):
            raise ValueError("Document citations must reference runbook evidence")
        if docs.retrieved_ids and not docs.indexed:
            raise ValueError("Cannot retrieve an unindexed document")
        return self


class Finding(StrictModel):
    id: uuid.UUID
    rule: str
    category: Category
    kind: Literal["blocker", "warning", "positive", "unknown"]
    title: str
    explanation: str
    remediation: str | None = None
    points: int = Field(ge=0)
    evidence_ids: list[uuid.UUID] = Field(min_length=1)


class ChecklistItem(StrictModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    title: str
    required: bool
    status: Literal["open"] = "open"


class ConfidenceComponent(StrictModel):
    category: Literal["changes", "reviews", "ci", "runbooks"]
    weight: int
    earned: int
    reason: str


class Decision(StrictModel):
    policy_version: str
    recommendation: Recommendation
    risk_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    category_scores: dict[Category, int]
    category_caps: dict[Category, int]
    confidence_components: list[ConfidenceComponent]
    summary: str
    findings: list[Finding]
    checklist: list[ChecklistItem]
