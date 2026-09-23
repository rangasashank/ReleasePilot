from typing import Literal

from pydantic import Field

from app.scoring.schemas import StrictModel


class AgentFinding(StrictModel):
    category: Literal["tests", "code_review", "complexity", "documentation"]
    title: str = Field(max_length=200)
    explanation: str = Field(max_length=1200)
    remediation: str = Field(max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    quotes: list[str] = Field(min_length=1, max_length=5)


class AgentHandoff(StrictModel):
    agent: Literal["change_ci", "knowledge", "reviewer"]
    status: Literal["completed", "partial"]
    summary: str = Field(max_length=1800)
    components: list[str] = Field(max_length=20)
    findings: list[AgentFinding] = Field(max_length=12)
    missing_evidence: list[str] = Field(max_length=12)
    contradictions: list[str] = Field(max_length=8)
