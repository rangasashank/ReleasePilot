from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Analysis, ReleaseCandidate
from tests.conftest import sign_in


def setup_service(client: TestClient) -> tuple[dict[str, str], str]:
    headers = sign_in(client)
    response = client.post("/api/v1/services", json={"name": "Checkout API"}, headers=headers)
    assert response.status_code == 201
    return {**headers, "Idempotency-Key": "test-analysis"}, response.json()["id"]


def test_persist_report_and_read_without_recomputing(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    response = client.post(
        "/api/v1/demo/analyses",
        json={"service_id": service_id, "scenario": "failed_ci"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["decision"]["recommendation"] == "NO_GO"
    assert report["source_mode"] == "demo"
    assert len(report["head_sha"]) == 40
    assert all(item["url"] is None for item in report["evidence"])
    db.expire_all()
    with patch("app.analyses.service.evaluate", side_effect=AssertionError("Must not recompute")):
        assert client.get(f"/api/v1/analyses/{report['id']}").json() == report
    ids = {item["id"] for item in report["evidence"]}
    assert all(set(item["evidence_ids"]) <= ids for item in report["decision"]["findings"])
    assert client.get("/api/v1/analyses").json()[0]["id"] == report["id"]


def test_idempotency_replay_and_conflict(client: TestClient, db: Session) -> None:
    headers, service_id = setup_service(client)
    body = {"service_id": service_id, "scenario": "safe"}
    first = client.post("/api/v1/demo/analyses", json=body, headers=headers)
    second = client.post("/api/v1/demo/analyses", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert db.scalar(select(func.count()).select_from(Analysis)) == 1
    assert db.scalar(select(func.count()).select_from(ReleaseCandidate)) == 1
    assert (
        client.post(
            "/api/v1/demo/analyses", json={**body, "scenario": "failed_ci"}, headers=headers
        ).status_code
        == 409
    )
    new = client.post(
        "/api/v1/demo/analyses", json=body, headers={**headers, "Idempotency-Key": "new-run"}
    )
    assert new.status_code == 201
    assert new.json()["id"] != first.json()["id"]
    assert {e["id"] for e in new.json()["evidence"]}.isdisjoint(
        {e["id"] for e in first.json()["evidence"]}
    )


def test_report_routes_enforce_workspace_scope(client: TestClient) -> None:
    headers, service_id = setup_service(client)
    created = client.post(
        "/api/v1/demo/analyses",
        json={"service_id": service_id, "scenario": "safe"},
        headers=headers,
    )
    analysis_id = created.json()["id"]
    other_headers = {**sign_in(client, 2), "Idempotency-Key": "test-analysis"}
    assert client.get("/api/v1/analyses").json() == []
    for suffix in ("", "/findings", "/evidence"):
        assert client.get(f"/api/v1/analyses/{analysis_id}{suffix}").status_code == 404
    assert (
        client.post(
            "/api/v1/demo/analyses",
            json={"service_id": service_id, "scenario": "safe"},
            headers=other_headers,
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "scenario,expected", [("safe", "GO"), ("failed_ci", "NO_GO"), ("missing_evidence", "CAUTION")]
)
def test_all_scenarios_through_api(client: TestClient, scenario: str, expected: str) -> None:
    headers, service_id = setup_service(client)
    response = client.post(
        "/api/v1/demo/analyses",
        json={"service_id": service_id, "scenario": scenario},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["decision"]["recommendation"] == expected


def test_create_requires_auth_csrf_valid_scenario_and_idempotency(client: TestClient) -> None:
    assert client.get("/api/v1/demo/scenarios").status_code == 401
    headers, service_id = setup_service(client)
    body = {"service_id": service_id, "scenario": "safe"}
    assert (
        client.post(
            "/api/v1/demo/analyses", json=body, headers={"Origin": "http://localhost:3000"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/demo/analyses",
            json=body,
            headers={k: v for k, v in headers.items() if k != "Idempotency-Key"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/demo/analyses", json={**body, "scenario": "fake"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/demo/analyses", json={**body, "workspace_id": "forged"}, headers=headers
        ).status_code
        == 422
    )
    assert len(client.get("/api/v1/demo/scenarios").json()) == 3
