"""Versioned heuristics. Identical snapshots always produce identical decisions."""

import uuid

from app.scoring.schemas import (
    Category,
    Check,
    ChecklistItem,
    ConfidenceComponent,
    Decision,
    EvidenceSnapshot,
    Finding,
    Recommendation,
)

POLICY_VERSION = "readiness-v1"
CONFIDENCE_THRESHOLD = 75
CAPS: dict[Category, int] = {"tests": 40, "code_review": 25, "complexity": 20, "documentation": 15}
FAILURES = {"failure", "timed_out"}


def evaluate(snapshot: EvidenceSnapshot) -> Decision:
    findings: list[Finding] = []

    def add(
        rule: str,
        category: Category,
        kind: str,
        title: str,
        explanation: str,
        points: int,
        evidence_ids: list[uuid.UUID],
        remediation: str | None = None,
    ) -> None:
        findings.append(
            Finding.model_validate(
                {
                    "id": uuid.uuid5(
                        snapshot.changes.evidence_id, f"releasepilot:{POLICY_VERSION}:{rule}"
                    ),
                    "rule": rule,
                    "category": category,
                    "kind": kind,
                    "title": title,
                    "explanation": explanation,
                    "points": points,
                    "evidence_ids": list(dict.fromkeys(evidence_ids)),
                    "remediation": remediation,
                }
            )
        )

    changes, reviews, ci, docs = (
        snapshot.changes,
        snapshot.reviews,
        snapshot.ci,
        snapshot.documents,
    )
    if changes.availability != "complete":
        add(
            "changes_incomplete",
            "complexity",
            "unknown",
            "Change evidence is incomplete",
            "The comparison is missing or truncated; unobserved changes are not assumed safe.",
            0,
            [changes.evidence_id],
            "Collect the complete base-to-target comparison.",
        )
    else:
        add(
            "changes_collected",
            "complexity",
            "positive",
            "Change comparison collected",
            f"Collected {len(changes.paths)} changed files for the resolved commit range.",
            0,
            [changes.evidence_id],
        )

    mismatched = [check for check in ci.checks if check.head_sha != snapshot.head_sha]
    if mismatched:
        add(
            "sha_mismatch",
            "tests",
            "blocker",
            "Check evidence targets another commit",
            "Checks for another SHA cannot establish readiness for this target.",
            40,
            [check.evidence_id for check in mismatched],
            "Collect checks for the exact target SHA.",
        )
    current: dict[str, Check] = {}
    for check in ci.checks:
        if check.head_sha == snapshot.head_sha:
            if check.name not in current or check.attempt > current[check.name].attempt:
                current[check.name] = check
    if ci.availability != "complete":
        add(
            "ci_incomplete",
            "tests",
            "unknown",
            "CI collection is incomplete",
            "Missing or partial collection cannot establish that required checks passed.",
            0,
            [ci.evidence_id],
            "Collect all check results for the target SHA.",
        )
    if not ci.policy_known or not ci.required_checks:
        add(
            "required_policy_unknown",
            "tests",
            "unknown",
            "Required-check policy is unknown",
            "An explicit, nonempty list of required checks is needed before GO is allowed.",
            0,
            [ci.evidence_id],
            "Identify the repository's required checks.",
        )
    if not current:
        add(
            "no_checks",
            "tests",
            "unknown",
            "No target CI checks found",
            "An empty check list is missing evidence, not a passing test suite.",
            25,
            [ci.evidence_id],
            "Run and collect the required CI checks.",
        )
    for name in ci.required_checks:
        required_check = current.get(name)
        if required_check is None or required_check.conclusion == "missing":
            add(
                f"required_missing:{name}",
                "tests",
                "unknown",
                f"Required check missing: {name}",
                "The required result has not been collected for this target.",
                25 if current else 0,
                [required_check.evidence_id if required_check else ci.evidence_id],
                f"Collect the required {name} result.",
            )
        elif required_check.conclusion in FAILURES:
            add(
                f"required_failed:{name}",
                "tests",
                "blocker",
                f"Required check failed: {name}",
                "The latest collected attempt failed. A required CI failure always blocks release.",
                40,
                [required_check.evidence_id],
                f"Fix and rerun {name} on the target SHA.",
            )
        elif required_check.conclusion != "success":
            add(
                f"required_not_passed:{name}",
                "tests",
                "warning",
                f"Required check is {required_check.conclusion}: {name}",
                "Only success satisfies a required check; pending, skipped, cancelled, "
                "and neutral do not.",
                20,
                [required_check.evidence_id],
                f"Obtain a successful {name} result on the target SHA.",
            )
    for name, check in sorted(current.items()):
        if name not in ci.required_checks and check.conclusion in FAILURES:
            add(
                f"optional_failed:{name}",
                "tests",
                "warning",
                f"Other check failed: {name}",
                "This check is not in the known required list; investigate its failure.",
                8,
                [check.evidence_id],
                f"Investigate the {name} failure.",
            )
        previous_failures = [
            item.evidence_id
            for item in ci.checks
            if item.name == name
            and item.head_sha == snapshot.head_sha
            and item.attempt < check.attempt
            and item.conclusion in FAILURES
        ]
        if check.conclusion == "success" and previous_failures:
            add(
                f"flaky:{name}",
                "tests",
                "warning",
                f"Check passed after a failure: {name}",
                "The latest attempt passed; earlier failures remain as possible "
                "flakiness evidence.",
                5,
                [*previous_failures, check.evidence_id],
                f"Review the earlier {name} failure.",
            )
    required_pass = bool(ci.policy_known and ci.required_checks) and all(
        name in current and current[name].conclusion == "success" for name in ci.required_checks
    )
    if required_pass and ci.availability == "complete" and not mismatched:
        add(
            "required_passed",
            "tests",
            "positive",
            "Required checks passed",
            "All known required checks succeeded on the exact target SHA.",
            0,
            [current[name].evidence_id for name in ci.required_checks],
        )

    if reviews.availability != "complete":
        add(
            "reviews_incomplete",
            "code_review",
            "unknown",
            "Review evidence is incomplete",
            "Unavailable review data cannot be treated as approval.",
            0,
            [reviews.evidence_id],
            "Collect current PR associations and review states.",
        )
    for review in reviews.reviews:
        if review.state != "approved":
            requested = review.state == "changes_requested"
            add(
                f"review:{review.evidence_id}",
                "code_review",
                "warning",
                "Requested changes remain unresolved" if requested else "Related PR lacks approval",
                "The collected review state does not establish approval.",
                15 if requested else 10,
                [review.evidence_id],
                "Resolve review feedback and obtain approval.",
            )
    if (
        reviews.availability == "complete"
        and reviews.reviews
        and all(review.state == "approved" for review in reviews.reviews)
    ):
        add(
            "reviews_approved",
            "code_review",
            "positive",
            "Related PRs are approved",
            "All collected related PRs have an approved review state.",
            0,
            [review.evidence_id for review in reviews.reviews],
        )
    if changes.direct_commits:
        add(
            "direct_commits",
            "code_review",
            "warning",
            "Commits without related PRs",
            f"{changes.direct_commits} commits have no associated PR; review "
            f"coverage is uncertain.",
            6,
            [changes.evidence_id],
            "Confirm review coverage for direct commits.",
        )

    paths = [path.lower() for path in changes.paths]
    migration = any("migration" in path or path.endswith(".sql") for path in paths)
    auth = any(
        any(part in path.split("/") for part in ("auth", "authentication", "authorization"))
        for path in paths
    )
    config = any(
        any(
            part in path.split("/")
            for part in ("deploy", "deployment", "config", "infrastructure", ".github")
        )
        or path.endswith(("dockerfile", ".tf"))
        for path in paths
    )
    large = len(paths) > 20 or changes.changed_lines > 1000
    very_large = len(paths) > 100 or changes.changed_lines > 5000
    for enabled, rule, title, explanation, points, action in [
        (
            large,
            "large_change",
            "Large change set",
            "Heuristic: over 20 files or 1,000 changed lines (10 points above 100 "
            "files or 5,000 lines).",
            10 if very_large else 5,
            "Review the release size and consider splitting it.",
        ),
        (
            migration,
            "migration",
            "Database migration detected",
            "Heuristic: a changed path contains migration or ends in .sql.",
            8,
            "Review migration safety, backups, and rollback steps.",
        ),
        (
            auth,
            "auth_change",
            "Authentication or authorization changed",
            "Heuristic: a changed path includes an auth, authentication, or "
            "authorization directory.",
            8,
            "Review authentication behavior and regression coverage.",
        ),
        (
            config,
            "config_change",
            "Deployment configuration changed",
            "Heuristic: deployment, infrastructure, or configuration paths changed.",
            5,
            "Verify the deployment configuration changes.",
        ),
    ]:
        if enabled:
            add(
                rule,
                "complexity",
                "warning",
                title,
                explanation,
                points,
                [changes.evidence_id],
                action,
            )
    if not docs.indexed:
        add(
            "no_runbook",
            "documentation",
            "unknown",
            "No runbook indexed",
            "Deployment instructions are unavailable for this release.",
            10,
            [docs.evidence_id],
            "Upload and index a deployment runbook.",
        )
    elif not docs.retrieved_ids or docs.availability != "complete":
        add(
            "runbook_retrieval_missing",
            "documentation",
            "unknown",
            "Relevant runbook evidence is missing",
            "An indexed document alone does not establish relevant deployment guidance.",
            0,
            [docs.evidence_id],
            "Retrieve relevant deployment instructions.",
        )
    if migration and not docs.migration_guidance_ids:
        add(
            "migration_guidance_missing",
            "documentation",
            "unknown",
            "Migration guidance not found",
            "A migration changed, but no matching backup or migration instructions were retrieved.",
            10,
            [changes.evidence_id, docs.evidence_id],
            "Find and verify backup and migration instructions.",
        )
    if docs.rollback_ids:
        add(
            "rollback_found",
            "documentation",
            "positive",
            "Rollback instructions available",
            "Relevant rollback guidance was retrieved; this is guidance, not proof of execution.",
            0,
            docs.rollback_ids,
        )
    if docs.migration_guidance_ids:
        add(
            "migration_guidance_found",
            "documentation",
            "positive",
            "Migration guidance available",
            "Backup guidance was retrieved. Its presence does not prove a backup was completed.",
            0,
            docs.migration_guidance_ids,
        )

    ci_observed = (
        ci.availability == "complete"
        and ci.policy_known
        and bool(ci.required_checks)
        and not mismatched
        and all(
            name in current and current[name].conclusion != "missing" for name in ci.required_checks
        )
    )
    components = [
        ConfidenceComponent(
            category=category,
            weight=weight,
            earned=weight if complete else 0,
            reason=reason if complete else missing,
        )
        for category, weight, complete, reason, missing in [
            (
                "changes",
                25,
                changes.availability == "complete",
                "Complete comparison collected.",
                "Comparison missing or partial.",
            ),
            (
                "reviews",
                20,
                reviews.availability == "complete",
                "PR/review collection complete.",
                "PR/review collection missing or partial.",
            ),
            (
                "ci",
                30,
                ci_observed,
                "Required-check policy and target results collected.",
                "Required-check policy or target results incomplete.",
            ),
            (
                "runbooks",
                25,
                docs.availability == "complete" and docs.indexed and bool(docs.retrieved_ids),
                "Relevant runbook excerpts retrieved.",
                "Relevant runbook evidence unavailable.",
            ),
        ]
    ]
    confidence = sum(component.earned for component in components)
    scores: dict[Category, int] = {
        category: min(cap, sum(item.points for item in findings if item.category == category))
        for category, cap in CAPS.items()
    }
    risk = sum(scores.values())
    blocker = any(finding.kind == "blocker" for finding in findings)
    mandatory_complete = (
        changes.availability == reviews.availability == ci.availability == "complete"
    )
    recommendation: Recommendation
    if blocker or risk >= 60:
        recommendation = "NO_GO"
    elif (
        risk >= 30
        or confidence < CONFIDENCE_THRESHOLD
        or not required_pass
        or not mandatory_complete
    ):
        recommendation = "CAUTION"
    else:
        recommendation = "GO"
    findings.sort(
        key=lambda item: (
            {"blocker": 0, "unknown": 1, "warning": 2, "positive": 3}[item.kind],
            item.rule,
        )
    )
    checklist = [
        ChecklistItem(
            id=uuid.uuid5(finding.id, "checklist"),
            finding_id=finding.id,
            title=finding.remediation,
            required=finding.kind in {"blocker", "unknown"},
        )
        for finding in findings
        if finding.remediation
    ]
    unknown_count = sum(finding.kind == "unknown" for finding in findings)
    summary = (
        f"Recommendation: {recommendation}. Observed risk is {risk}/100; "
        f"evidence confidence is {confidence}/100. "
        + (
            "A hard blocker prevents release. "
            if blocker
            else "No deterministic hard blocker was found. "
        )
        + (
            f"There are {unknown_count} missing-evidence signals to review."
            if unknown_count
            else "Review the cited findings and checklist before making a deployment decision."
        )
    )
    return Decision(
        policy_version=POLICY_VERSION,
        recommendation=recommendation,
        risk_score=risk,
        confidence_score=confidence,
        category_scores=scores,
        category_caps=CAPS,
        confidence_components=components,
        summary=summary,
        findings=findings,
        checklist=checklist,
    )
