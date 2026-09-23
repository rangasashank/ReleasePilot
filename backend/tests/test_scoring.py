import uuid

import pytest
from pydantic import ValidationError

from app.analyses.fixtures import Scenario, fixture
from app.scoring.engine import evaluate
from app.scoring.schemas import EvidenceSnapshot


@pytest.mark.parametrize(
    "scenario,recommendation,risk,confidence",
    [
        ("safe", "GO", 0, 100),
        ("failed_ci", "NO_GO", 48, 100),
        ("missing_evidence", "CAUTION", 35, 25),
    ],
)
def test_fixture_decisions(
    scenario: Scenario, recommendation: str, risk: int, confidence: int
) -> None:
    snapshot = fixture(scenario)
    decision = evaluate(snapshot)
    assert (decision.recommendation, decision.risk_score, decision.confidence_score) == (
        recommendation,
        risk,
        confidence,
    )
    assert evaluate(snapshot) == decision
    assert decision.risk_score == sum(decision.category_scores.values())
    owned = {item.id for item in snapshot.evidence}
    assert all(set(finding.evidence_ids) <= owned for finding in decision.findings)
    assert all(item.finding_id in {f.id for f in decision.findings} for item in decision.checklist)


@pytest.mark.parametrize(
    "conclusion,expected",
    [
        ("failure", "NO_GO"),
        ("timed_out", "NO_GO"),
        ("pending", "CAUTION"),
        ("missing", "CAUTION"),
        ("cancelled", "CAUTION"),
        ("neutral", "CAUTION"),
        ("skipped", "CAUTION"),
        ("success", "GO"),
    ],
)
def test_required_check_states(conclusion: str, expected: str) -> None:
    raw = fixture("safe").model_dump()
    raw["ci"]["checks"][0]["conclusion"] = conclusion
    decision = evaluate(EvidenceSnapshot.model_validate(raw))
    assert decision.recommendation == expected
    assert any(f.kind == "blocker" for f in decision.findings) == (expected == "NO_GO")


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "unknown_policy",
        "empty_policy",
        "partial_ci",
        "wrong_sha",
        "partial_changes",
        "missing_reviews",
    ],
)
def test_missing_mandatory_evidence_never_go(mutation: str) -> None:
    raw = fixture("safe").model_dump()
    if mutation == "empty":
        raw["ci"]["checks"] = []
    elif mutation == "unknown_policy":
        raw["ci"]["policy_known"] = False
    elif mutation == "empty_policy":
        raw["ci"]["required_checks"] = []
    elif mutation == "partial_ci":
        raw["ci"]["availability"] = "partial"
    elif mutation == "wrong_sha":
        raw["ci"]["checks"][0]["head_sha"] = "e" * 40
    elif mutation == "partial_changes":
        raw["changes"]["availability"] = "partial"
    else:
        raw["reviews"]["availability"] = "missing"
    decision = evaluate(EvidenceSnapshot.model_validate(raw))
    assert decision.recommendation != "GO"
    assert decision.confidence_score < 100
    if mutation == "wrong_sha":
        assert any(f.rule == "sha_mismatch" and f.kind == "blocker" for f in decision.findings)


def test_successful_rerun_keeps_failure_as_flakiness() -> None:
    raw = fixture("safe").model_dump()
    first = raw["ci"]["checks"][0]
    first["conclusion"] = "failure"
    new_id = uuid.uuid4()
    evidence = {**raw["evidence"][0], "id": new_id, "source_type": "check"}
    raw["evidence"].append(evidence)
    raw["ci"]["checks"].append(
        {**first, "evidence_id": new_id, "attempt": 2, "conclusion": "success"}
    )
    decision = evaluate(EvidenceSnapshot.model_validate(raw))
    assert decision.recommendation == "GO"
    assert decision.risk_score == 5
    finding = next(f for f in decision.findings if f.rule == "flaky:unit")
    assert set(finding.evidence_ids) == {first["evidence_id"], new_id}
    assert not any(f.kind == "blocker" for f in decision.findings)
    # Input ordering never changes which attempt is current.
    raw["ci"]["checks"].reverse()
    assert evaluate(EvidenceSnapshot.model_validate(raw)) == decision


def test_category_caps_and_sixty_point_no_go() -> None:
    raw = fixture("safe").model_dump()
    raw["ci"]["checks"][0]["conclusion"] = "pending"  # 20, not a hard blocker
    raw["reviews"]["reviews"][0]["state"] = "changes_requested"  # 15
    raw["changes"].update(
        paths=["auth/migrations/new.sql", "config/release.tf"]
        + [f"src/{i}.py" for i in range(101)],
        changed_lines=6000,
        direct_commits=2,
    )
    raw["documents"].update(
        indexed=False,
        retrieved_ids=[],
        rollback_ids=[],
        migration_guidance_ids=[],
        availability="missing",
    )
    decision = evaluate(EvidenceSnapshot.model_validate(raw))
    assert decision.category_scores == {
        "tests": 20,
        "code_review": 21,
        "complexity": 20,
        "documentation": 15,
    }
    assert decision.risk_score == 76
    assert decision.recommendation == "NO_GO"
    assert not any(f.kind == "blocker" for f in decision.findings)


@pytest.mark.parametrize("lines,expected_points", [(1000, 0), (1001, 5), (5000, 5), (5001, 10)])
def test_complexity_boundaries(lines: int, expected_points: int) -> None:
    raw = fixture("safe").model_dump()
    raw["changes"]["changed_lines"] = lines
    assert (
        evaluate(EvidenceSnapshot.model_validate(raw)).category_scores["complexity"]
        == expected_points
    )


def test_failure_does_not_reduce_evidence_confidence() -> None:
    assert evaluate(fixture("failed_ci")).confidence_score == 100


def test_optional_failure_is_warning_not_required_blocker() -> None:
    raw = fixture("safe").model_dump()
    raw["ci"]["required_checks"] = ["unit"]
    raw["ci"]["checks"][1]["conclusion"] = "failure"
    decision = evaluate(EvidenceSnapshot.model_validate(raw))
    assert decision.risk_score == 8
    assert decision.recommendation == "GO"
    assert not any(f.kind == "blocker" for f in decision.findings)


@pytest.mark.parametrize(
    "bad_input",
    [
        "foreign_id",
        "duplicate_id",
        "duplicate_attempt",
        "same_sha",
        "bad_sha",
        "wrong_source",
        "invented_guidance",
    ],
)
def test_snapshot_rejects_invalid_evidence_graph(bad_input: str) -> None:
    raw = fixture("safe").model_dump()
    if bad_input == "foreign_id":
        raw["ci"]["checks"][0]["evidence_id"] = uuid.uuid4()
    elif bad_input == "duplicate_id":
        raw["evidence"].append(raw["evidence"][0])
    elif bad_input == "duplicate_attempt":
        raw["ci"]["checks"].append(raw["ci"]["checks"][0])
    elif bad_input == "same_sha":
        raw["head_sha"] = raw["base_sha"]
    elif bad_input == "bad_sha":
        raw["head_sha"] = "main"
    elif bad_input == "wrong_source":
        raw["ci"]["checks"][0]["evidence_id"] = raw["changes"]["evidence_id"]
    else:
        raw["documents"]["migration_guidance_ids"] = [uuid.uuid4()]
    with pytest.raises(ValidationError):
        EvidenceSnapshot.model_validate(raw)
