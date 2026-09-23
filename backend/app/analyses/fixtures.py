"""Synthetic evidence. These fixtures never claim to be live GitHub results."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from app.scoring.schemas import Evidence, EvidenceSnapshot

Scenario = Literal["safe", "failed_ci", "missing_evidence"]
SCENARIOS: dict[Scenario, tuple[str, str]] = {
    "safe": (
        "Safe release",
        "A small change with approved review, passing checks, and runbook guidance.",
    ),
    "failed_ci": (
        "Failed required CI",
        "A migration release with a failed required integration test.",
    ),
    "missing_evidence": (
        "Missing evidence",
        "A small change with unavailable reviews, CI, and runbook evidence.",
    ),
}


def fixture(scenario: Scenario, namespace: uuid.UUID = uuid.NAMESPACE_URL) -> EvidenceSnapshot:
    captured_at = datetime(2026, 9, 6, tzinfo=UTC)
    records: list[Evidence] = []

    def evidence(key: str, kind: str, title: str, excerpt: str, locator: str) -> str:
        evidence_id = uuid.uuid5(namespace, f"releasepilot:fixture:v1:{scenario}:{key}")
        records.append(
            Evidence.model_validate(
                {
                    "id": evidence_id,
                    "source_type": kind,
                    "title": title,
                    "excerpt": excerpt,
                    "locator": f"Fixture v1 · {locator}",
                    "captured_at": captured_at,
                }
            )
        )
        return str(evidence_id)

    missing = scenario == "missing_evidence"
    failed = scenario == "failed_ci"
    head_sha = {"safe": "b", "failed_ci": "c", "missing_evidence": "d"}[scenario] * 40
    comparison = evidence(
        "comparison",
        "comparison",
        "Release comparison",
        "migrations/004_add_index.sql: +12 -0" if failed else "src/cart.py: +8 -3",
        "compare aaaaaaa… → " + head_sha[:7] + "…",
    )
    review_collection = evidence(
        "reviews",
        "collection",
        "Review collection",
        "Review provider unavailable; no approval inferred."
        if missing
        else "One related PR and its current review collected.",
        "reviews",
    )
    ci_collection = evidence(
        "ci",
        "collection",
        "Required-check collection",
        "CI results and required-check policy are unavailable."
        if missing
        else "Required checks: unit, integration. Results belong to the target SHA.",
        "checks",
    )
    doc_collection = evidence(
        "docs",
        "collection",
        "Runbook retrieval",
        "No runbook indexed or retrieved."
        if missing
        else "Deployment runbook v1 indexed; rollback and backup guidance retrieved.",
        "knowledge search",
    )
    checks = []
    reviews = []
    retrieved = []
    rollback = []
    migration = []
    if not missing:
        review_id = evidence(
            "pr",
            "review",
            "PR #42 · Review",
            "Current review state: APPROVED. No unresolved change requests.",
            "pull/42/reviews",
        )
        reviews.append({"evidence_id": review_id, "state": "approved"})
        for name in ("unit", "integration"):
            conclusion = "failure" if failed and name == "integration" else "success"
            check_id = evidence(
                name,
                "check",
                f"{name.title()} tests · {conclusion}",
                f"name={name}; conclusion={conclusion}; attempt=1; head_sha={head_sha}",
                f"checks/{name}/attempt/1",
            )
            checks.append(
                {
                    "evidence_id": check_id,
                    "name": name,
                    "head_sha": head_sha,
                    "conclusion": conclusion,
                    "attempt": 1,
                }
            )
        rollback.append(
            evidence(
                "rollback",
                "runbook",
                "Deployment runbook · Rollback",
                "If the release fails health checks, redeploy the previous application "
                "version and verify recovery.",
                "Deployment runbook v1 / Rollback",
            )
        )
        migration.append(
            evidence(
                "backup",
                "runbook",
                "Deployment runbook · Database changes",
                "Before applying a database migration, verify a recent backup and test "
                "the migration in staging.",
                "Deployment runbook v1 / Database changes",
            )
        )
        retrieved = rollback + migration
    return EvidenceSnapshot.model_validate(
        {
            "base_sha": "a" * 40,
            "head_sha": head_sha,
            "evidence": records,
            "changes": {
                "evidence_id": comparison,
                "availability": "complete",
                "paths": ["migrations/004_add_index.sql"] if failed else ["src/cart.py"],
                "changed_lines": 12 if failed else 11,
                "direct_commits": 0,
            },
            "reviews": {
                "evidence_id": review_collection,
                "availability": "missing" if missing else "complete",
                "reviews": reviews,
            },
            "ci": {
                "evidence_id": ci_collection,
                "availability": "missing" if missing else "complete",
                "policy_known": not missing,
                "required_checks": [] if missing else ["unit", "integration"],
                "checks": checks,
            },
            "documents": {
                "evidence_id": doc_collection,
                "availability": "missing" if missing else "complete",
                "indexed": not missing,
                "retrieved_ids": retrieved,
                "rollback_ids": rollback,
                "migration_guidance_ids": migration if failed else [],
            },
        }
    )
