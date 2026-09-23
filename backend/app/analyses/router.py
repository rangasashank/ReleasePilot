import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.analyses.fixtures import SCENARIOS
from app.analyses.schemas import AnalysisReport, AnalysisSummary, DemoAnalysisInput, ScenarioOutput
from app.analyses.service import create_demo_analysis, get_report, recent_analyses
from app.auth import Identity, current_identity, mutation_identity
from app.db import get_db
from app.scoring.schemas import Evidence, Finding

router = APIRouter(prefix="/api/v1", tags=["analyses"])


@router.get("/demo/scenarios", response_model=list[ScenarioOutput])
def scenarios(identity: Identity = Depends(current_identity)) -> list[ScenarioOutput]:
    return [
        ScenarioOutput(id=key, title=value[0], description=value[1])
        for key, value in SCENARIOS.items()
    ]


@router.post("/demo/analyses", response_model=AnalysisReport, status_code=201)
def create(
    data: DemoAnalysisInput,
    idempotency_key: str = Header(min_length=1, max_length=128),
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> AnalysisReport:
    return create_demo_analysis(db, identity.workspace.id, data, idempotency_key)


@router.get("/analyses", response_model=list[AnalysisSummary])
def recent(
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[AnalysisSummary]:
    return recent_analyses(db, identity.workspace.id, limit, offset)


@router.get("/analyses/{analysis_id}", response_model=AnalysisReport)
def report(
    analysis_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> AnalysisReport:
    return get_report(db, identity.workspace.id, analysis_id)


@router.get("/analyses/{analysis_id}/findings", response_model=list[Finding])
def findings(
    analysis_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> list[Finding]:
    return get_report(db, identity.workspace.id, analysis_id).decision.findings


@router.get("/analyses/{analysis_id}/evidence", response_model=list[Evidence])
def evidence(
    analysis_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> list[Evidence]:
    return get_report(db, identity.workspace.id, analysis_id).evidence
