import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import pytest
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import IntegrationError
from app.github.client import GitHubClient, cache_prefix
from app.mcp_tools.server import execute
from app.models import Repository, Workspace


class NoCache:
    def get(self, *args: object) -> None:
        raise redis.ConnectionError()

    def setex(self, *args: object) -> None:
        raise redis.ConnectionError()


@pytest.fixture
def repository(db: Session) -> Repository:
    workspace = db.scalar(select(Workspace))
    assert workspace
    repo = Repository(
        workspace_id=workspace.id,
        github_id=42,
        full_name="owner/repo",
        default_branch="main",
        auth_mode="public",
    )
    db.add(repo)
    db.commit()
    return repo


def test_redis_outage_and_inflight_dedup(db: Session, repository: Repository) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"sha": "b" * 40})

    with (
        patch("app.github.client.get_engine", return_value=db.get_bind()),
        patch("app.github.client.cache_connection", return_value=NoCache()),
    ):
        client = GitHubClient(repository, httpx.MockTransport(handle))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.resolve, "main") for _ in range(2)]
            assert [f.result() for f in futures] == ["b" * 40] * 2
        client.close()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "code,headers",
    [(429, {"retry-after": "60"}), (403, {"x-ratelimit-remaining": "0", "retry-after": "10"})],
)
def test_rate_limit_shared_cooldown(
    db: Session, repository: Repository, code: int, headers: dict[str, str]
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(code, headers=headers, json={"message": "rate limit"})

    with (
        patch("app.github.client.get_engine", return_value=db.get_bind()),
        patch("app.github.client.cache_connection", return_value=NoCache()),
    ):
        for _ in range(2):
            client = GitHubClient(repository, httpx.MockTransport(handle))
            with pytest.raises(IntegrationError) as caught:
                client.resolve("main")
            assert caught.value.code == "GITHUB_RATE_LIMIT"
            assert caught.value.retry_after and caught.value.retry_after > 0
            client.close()
    assert len(calls) == 1


def test_unauthorized_and_write_tools_fail_before_provider_access() -> None:
    for agent, tool in [
        ("reviewer", "compare_commits"),
        ("knowledge", "list_check_runs"),
        ("change_ci", "execute_shell"),
        ("knowledge", "deploy_release"),
    ]:
        with pytest.raises(ValueError, match="not allowed"):
            execute(tool, {}, {"agent": agent})


def test_cache_namespaces_never_cross_workspaces(repository: Repository) -> None:
    first = cache_prefix(repository)
    repository.workspace_id = uuid.uuid4()
    assert first != cache_prefix(repository)
    second = cache_prefix(repository)
    repository.installation_id = 123
    assert second != cache_prefix(repository)


def test_github_response_body_is_bounded(db: Session, repository: Repository) -> None:
    with (
        patch("app.github.client.get_engine", return_value=db.get_bind()),
        patch("app.github.client.cache_connection", return_value=NoCache()),
    ):
        client = GitHubClient(
            repository, httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 4_000_001))
        )
        with pytest.raises(IntegrationError) as caught:
            client.resolve("main")
        assert caught.value.code == "EVIDENCE_LIMIT"
        client.close()


def test_collector_preserves_failed_required_check_and_app_identity() -> None:
    from typing import Any, cast

    from app.github.collector import collect
    from app.scoring.engine import evaluate

    class FixtureGitHub:
        prefix = "/repos/owner/repo"

        def compare(self, base: str, head: str) -> dict[str, Any]:
            return {
                "files": [{"filename": "cart.py", "additions": 1}],
                "commits": [],
                "total_commits": 0,
            }

        def pages(self, path: str, *args: Any, **kwargs: Any) -> tuple[list[Any], bool]:
            if path.endswith("check-runs"):
                return [
                    {
                        "id": 1,
                        "name": "unit",
                        "status": "completed",
                        "conclusion": "failure",
                        "head_sha": "b" * 40,
                        "app": {"id": 99},
                    },
                    {
                        "id": 2,
                        "name": "unit",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "b" * 40,
                        "app": {"id": 100},
                    },
                ], True
            return [], True

        def get(self, path: str, **kwargs: Any) -> Any:
            return (
                {"checks": [{"context": "unit", "app_id": 99}], "contexts": ["unit"]}
                if path.endswith("required_status_checks")
                else []
            )

    snapshot = collect(cast(Any, FixtureGitHub()), "a" * 40, "b" * 40, uuid.uuid4(), "main")
    assert snapshot.ci.required_checks == ["unit [app:99]"]
    assert evaluate(snapshot).recommendation == "NO_GO"
