import uuid
from datetime import UTC, datetime
from typing import Any

from app.errors import IntegrationError
from app.github.client import GitHubClient
from app.scoring.schemas import EvidenceSnapshot


def collect(
    client: GitHubClient, base: str, head: str, namespace: uuid.UUID, branch: str | None = None
) -> EvidenceSnapshot:
    evidence: list[dict[str, Any]] = []

    def add(key: str, kind: str, title: str, excerpt: str, url: str | None = None) -> str:
        identifier = str(uuid.uuid5(namespace, key))
        evidence.append(
            {
                "id": identifier,
                "source_type": kind,
                "title": title[:200],
                "excerpt": excerpt[:12000],
                "locator": key[:500],
                "url": url,
                "captured_at": datetime.now(UTC),
            }
        )
        return identifier

    comparison = client.compare(base, head)
    if comparison.get("status", "ahead") in ("behind", "diverged", "identical"):
        raise IntegrationError("INVALID_RELEASE_RANGE", "Target must advance from the base commit")
    files = comparison.get("files", [])[:300]
    commits = comparison.get("commits", [])[:100]
    complete_changes = len(files) < 300 and comparison.get("total_commits", 0) <= len(commits)
    comparison_id = add(
        "comparison",
        "comparison",
        "GitHub commit comparison",
        "\n".join(
            f"{f['filename']}: +{f.get('additions', 0)} -{f.get('deletions', 0)}\n"
            f"{f.get('patch', '')[:800]}"
            for f in files
        ),
        comparison.get("html_url"),
    )
    ci_collection_id = add(
        "ci_collection",
        "collection",
        "GitHub checks collection",
        "Collected checks for the exact target SHA.",
    )
    reviews_collection_id = add(
        "reviews_collection",
        "collection",
        "GitHub PR and review collection",
        "Related PRs are associated with commits in the comparison.",
    )
    docs_id = add(
        "knowledge_collection",
        "collection",
        "Runbook retrieval",
        "No runbook passages retrieved yet.",
    )
    checks: list[dict[str, Any]] = []
    required: list[str] = []
    policy_known = False
    policy_incomplete = False
    ci_complete = True
    review_complete = True
    reviews: list[dict[str, Any]] = []
    direct_commits = 0

    def optional_failure(exc: IntegrationError) -> None:
        if exc.retry_after is not None:
            raise exc  # Reschedule with saved checkpoints rather than hammer the provider.

    try:
        raw_checks, ci_complete = client.pages(
            f"{client.prefix}/commits/{head}/check-runs",
            "check_runs",
            fresh=True,
            params={"filter": "all"},
        )
        statuses, statuses_complete = client.pages(
            f"{client.prefix}/commits/{head}/statuses", fresh=True
        )
        ci_complete = ci_complete and statuses_complete
        attempts: dict[str, int] = {}
        # Provider IDs/timestamps define chronology; the model cannot pick a passing attempt.
        combined = [
            {
                **item,
                "_name": item["name"],
                "_time": item.get("started_at") or "",
                "_result": item.get("conclusion")
                if item.get("status") == "completed"
                else "pending",
            }
            for item in raw_checks
        ]
        combined += [
            {
                **item,
                "_name": item["context"],
                "head_sha": head,
                "_time": item.get("created_at") or "",
                "html_url": item.get("target_url"),
                "_result": {"error": "failure"}.get(item["state"], item["state"]),
            }
            for item in statuses
        ]
        for item in sorted(combined, key=lambda row: (row["_time"], row.get("id", 0))):
            name = item["_name"]
            # Bind App check identity to app ID to avoid name collisions spoofing required checks.
            app_id = item.get("app", {}).get("id")
            identity = f"{name} [app:{app_id}]" if app_id else name
            attempts[identity] = attempts.get(identity, 0) + 1
            conclusion = item.get("_result") or "missing"
            if conclusion not in {
                "success",
                "failure",
                "cancelled",
                "skipped",
                "neutral",
                "pending",
                "missing",
                "timed_out",
            }:
                conclusion = (
                    "failure" if conclusion in {"action_required", "startup_failure"} else "missing"
                )
            url = item.get("html_url")
            if url and not str(url).startswith("https://"):
                url = None
            evidence_id = add(
                f"check:{identity}:{item.get('id')}",
                "check",
                f"{name}: {conclusion}",
                f"Check {identity}; conclusion={conclusion}; "
                f"SHA={item.get('head_sha', head)}; attempt={attempts[identity]}",
                url,
            )
            checks.append(
                {
                    "evidence_id": evidence_id,
                    "name": identity,
                    "head_sha": item.get("head_sha", head),
                    "conclusion": conclusion,
                    "attempt": attempts[identity],
                }
            )
        if branch:
            from urllib.parse import quote

            try:
                protection = client.get(
                    f"{client.prefix}/branches/{quote(branch, safe='')}"
                    "/protection/required_status_checks",
                    fresh=True,
                )
                for item in protection.get("checks", []):
                    name = item["context"]
                    required.append(
                        f"{name} [app:{item['app_id']}]" if item.get("app_id") else name
                    )
                bound_contexts = {c["context"] for c in protection.get("checks", [])}
                required.extend(
                    c for c in protection.get("contexts", []) if c not in bound_contexts
                )
                # Unbound contexts match only a unique observed identity.
                required = [
                    next((c["name"] for c in checks if c["name"].split(" [app:")[0] == name), name)
                    if len({c["name"] for c in checks if c["name"].split(" [app:")[0] == name}) == 1
                    else name
                    for name in required
                ]
                policy_known = bool(required)
            except IntegrationError as exc:
                policy_incomplete = True
                optional_failure(exc)
            try:
                rules = client.get(
                    f"{client.prefix}/rules/branches/{quote(branch, safe='')}", fresh=True
                )
                for rule in rules:
                    if rule.get("type") == "required_status_checks":
                        for check in rule.get("parameters", {}).get("required_status_checks", []):
                            name = check["context"]
                            integration = check.get("integration_id")
                            required.append(f"{name} [app:{integration}]" if integration else name)
                policy_known = bool(required)
            except IntegrationError as exc:
                policy_incomplete = True
                optional_failure(exc)
    except IntegrationError as exc:
        optional_failure(exc)
        ci_complete = False
        evidence[1]["excerpt"] = (
            f"Check collection incomplete: {exc.code}. No passing result inferred."
        )

    policy_known = policy_known and not policy_incomplete
    pull_requests: dict[int, dict[str, Any]] = {}
    if len(commits) > 20:
        review_complete = False
    for commit in commits[:20]:
        try:
            prs, complete = client.pages(
                f"{client.prefix}/commits/{commit['sha']}/pulls", fresh=True, max_pages=1
            )
            review_complete &= complete
            if not prs:
                direct_commits += 1
            for pr in prs:
                pull_requests[pr["number"]] = pr
        except IntegrationError as exc:
            optional_failure(exc)
            review_complete = False
    if len(pull_requests) > 15:
        review_complete = False
    for number, pr in list(pull_requests.items())[:15]:
        try:
            items, complete = client.pages(
                f"{client.prefix}/pulls/{number}/reviews", fresh=True, max_pages=2
            )
            review_complete &= complete
            current_reviews: dict[str, dict[str, Any]] = {}
            for review in sorted(items, key=lambda row: row.get("submitted_at") or ""):
                if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                    current_reviews[str(review.get("user", {}).get("id"))] = review
            states = [item["state"] for item in current_reviews.values()]
            state = "changes_requested" if "CHANGES_REQUESTED" in states else "unapproved"
            if state != "changes_requested" and any(
                item["state"] == "APPROVED"
                and item.get("commit_id") == pr.get("head", {}).get("sha")
                for item in current_reviews.values()
            ):
                state = "approved"
            eid = add(
                f"pr:{number}",
                "review",
                f"PR #{number}: {pr['title']}",
                f"Current review state={state}. {pr.get('body') or ''}"[:4000],
                pr.get("html_url"),
            )
            reviews.append({"evidence_id": eid, "state": state})
        except IntegrationError as exc:
            optional_failure(exc)
            review_complete = False
    return EvidenceSnapshot.model_validate(
        {
            "base_sha": base,
            "head_sha": head,
            "evidence": evidence,
            "changes": {
                "evidence_id": comparison_id,
                "availability": "complete" if complete_changes else "partial",
                "paths": [item["filename"] for item in files],
                "changed_lines": sum(
                    item.get("additions", 0) + item.get("deletions", 0) for item in files
                ),
                "direct_commits": direct_commits,
            },
            "ci": {
                "evidence_id": ci_collection_id,
                "availability": "complete" if ci_complete else "partial",
                "policy_known": policy_known,
                "required_checks": sorted(set(required)),
                "checks": checks,
            },
            "reviews": {
                "evidence_id": reviews_collection_id,
                "availability": "complete" if review_complete else "partial",
                "reviews": reviews,
            },
            "documents": {
                "evidence_id": docs_id,
                "availability": "missing",
                "indexed": False,
                "retrieved_ids": [],
            },
        }
    )
