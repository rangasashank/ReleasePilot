"""One bounded, cached, quota-aware GitHub client for collectors and MCP tools."""

import hashlib
import json
import random
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import jwt
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.errors import IntegrationError
from app.models import ProviderQuota, Repository

_token_lock = threading.Lock()
_tokens: dict[int, tuple[str, float]] = {}


def installation_token(installation_id: int, refresh: bool = False) -> str:
    settings = get_settings()
    with _token_lock:
        cached = _tokens.get(installation_id)
        if cached and cached[1] > time.time() and not refresh:
            return cached[0]
        if not settings.github_app_id or not (
            settings.github_app_private_key_file
            or settings.github_app_private_key.get_secret_value()
        ):
            raise IntegrationError("GITHUB_NOT_CONFIGURED", "Configure the GitHub App credentials.")
        private_key = (
            settings.github_app_private_key.get_secret_value()
            or Path(settings.github_app_private_key_file).read_text()
        )
        signed = jwt.encode(
            {
                "iat": int(time.time()) - 30,
                "exp": int(time.time()) + 540,
                "iss": settings.github_app_id,
            },
            private_key,
            algorithm="RS256",
        )
        response = httpx.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {signed}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if response.status_code != 201:
            raise IntegrationError(
                "GITHUB_AUTH", "GitHub App access is unavailable. Reconnect the installation."
            )
        token = str(response.json()["token"])
        _tokens[installation_id] = (token, time.time() + 3000)
        return token


def cache_connection() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=0.3,
        socket_timeout=0.5,
        decode_responses=True,
    )


def cache_prefix(repo: Repository) -> str:
    return f"rp:{repo.workspace_id}:{repo.installation_id or 'public'}:{repo.github_id}:"


def invalidate(repo: Repository) -> None:
    try:
        cache = cache_connection()
        for key in cache.scan_iter(match=cache_prefix(repo) + "*", count=100):
            cache.delete(key)
    except redis.RedisError:
        pass  # The durable snapshot never depends on Redis.


class GitHubClient:
    def __init__(self, repo: Repository, transport: httpx.BaseTransport | None = None) -> None:
        self.repo = repo
        self.requests = 0
        self._lock = threading.Lock()
        self._memo: dict[str, Any] = {}
        self.http = httpx.Client(
            base_url="https://api.github.com",
            timeout=15,
            follow_redirects=False,
            transport=transport,
        )
        self.prefix = f"/repos/{repo.full_name}"

    def _request(
        self, path: str, params: dict[str, Any] | None, headers: dict[str, str]
    ) -> httpx.Response:
        with self.http.stream("GET", path, params=params, headers=headers) as response:
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 4_000_000:
                    raise IntegrationError("EVIDENCE_LIMIT", "GitHub response exceeds 4 MB")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
            )

    def close(self) -> None:
        self.http.close()

    def get(
        self, path: str, *, params: dict[str, Any] | None = None, ttl: int = 60, fresh: bool = False
    ) -> Any:
        memo_key = json.dumps([path, params], sort_keys=True)
        with self._lock:
            if memo_key not in self._memo:
                self._memo[memo_key] = self._get(path, params=params, ttl=ttl, fresh=fresh)
            return self._memo[memo_key]

    def _get(self, path: str, *, params: dict[str, Any] | None, ttl: int, fresh: bool) -> Any:
        if not path.startswith("/repos/") or ".." in path.split("/") or path.startswith("//"):
            raise IntegrationError("GITHUB_SCOPE", "Only repository API paths are allowed")
        self.requests += 1
        if self.requests > get_settings().max_github_requests:
            raise IntegrationError(
                "EVIDENCE_LIMIT", "Evidence collection reached its request budget."
            )
        key = (
            cache_prefix(self.repo)
            + hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
        )
        cache = cache_connection()
        if not fresh:
            try:
                cached = cache.get(key)
                if cached:
                    cache.incr("rp:metrics:cache_hits")
                    return json.loads(str(cached))
            except (redis.RedisError, ValueError):
                pass
        installation_key = str(self.repo.installation_id or "public")
        # Serialize misses across API/worker/MCP processes with a short, bounded row lock.
        with Session(get_engine()) as db:
            if db.get(ProviderQuota, installation_key) is None:
                from sqlalchemy.exc import IntegrityError

                try:
                    db.add(ProviderQuota(installation_key=installation_key))
                    db.commit()
                except IntegrityError:
                    db.rollback()
            quota = db.scalar(
                select(ProviderQuota)
                .where(ProviderQuota.installation_key == installation_key)
                .with_for_update()
            )
            assert quota
            blocked = quota.blocked_until
            if blocked and blocked.replace(tzinfo=UTC) > datetime.now(UTC):
                raise IntegrationError(
                    "GITHUB_RATE_LIMIT",
                    "Waiting for GitHub quota.",
                    max(1, int((blocked.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds())),
                )
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.repo.installation_id:
                headers["Authorization"] = f"Bearer {installation_token(self.repo.installation_id)}"
            try:
                response = self._request(path, params, headers)
                if response.status_code == 401 and self.repo.installation_id:
                    headers["Authorization"] = (
                        f"Bearer {installation_token(self.repo.installation_id, refresh=True)}"
                    )
                    response = self._request(path, params, headers)
            except httpx.HTTPError as exc:
                raise IntegrationError(
                    "GITHUB_NETWORK", "GitHub could not be reached.", 15
                ) from exc
            quota.request_count += 1
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining and remaining.isdigit():
                quota.remaining = int(remaining)
            reset = response.headers.get("x-ratelimit-reset")
            if reset and reset.isdigit():
                quota.reset_at = datetime.fromtimestamp(int(reset), UTC)
            limited = response.status_code == 429 or (
                response.status_code == 403
                and (
                    remaining == "0"
                    or "retry-after" in response.headers
                    or "rate limit" in response.text.lower()
                    or "abuse" in response.text.lower()
                )
            )
            if limited:
                retry = response.headers.get("retry-after", "")
                delay = (
                    int(retry)
                    if retry.isdigit()
                    else max(60, int(reset or time.time() + 60) - int(time.time()))
                )
                delay = min(max(delay, 1), 86400) + random.randint(1, 5)
                quota.blocked_until = datetime.now(UTC) + timedelta(seconds=delay)
                db.commit()
                raise IntegrationError("GITHUB_RATE_LIMIT", "Waiting for GitHub quota.", delay)
            db.commit()
            if response.status_code >= 500:
                raise IntegrationError(
                    "GITHUB_UNAVAILABLE", "GitHub is temporarily unavailable.", 20
                )
            if response.status_code in (401, 403):
                raise IntegrationError(
                    "GITHUB_PERMISSION", "GitHub permission is missing or revoked."
                )
            if response.status_code == 404:
                raise IntegrationError(
                    "GITHUB_NOT_FOUND", "Repository, ref, or evidence is inaccessible."
                )
            if response.status_code != 200:
                raise IntegrationError("GITHUB_RESPONSE", "GitHub rejected this request.")
            if len(response.content) > 4_000_000:
                raise IntegrationError(
                    "EVIDENCE_LIMIT", "GitHub response exceeds the evidence size limit."
                )
            data = response.json()
        try:
            cache.setex(key, max(1, ttl), json.dumps(data))
            cache.incr("rp:metrics:provider_requests")
        except redis.RedisError:
            pass
        return data

    def pages(
        self,
        path: str,
        key: str | None = None,
        *,
        fresh: bool = False,
        max_pages: int = 3,
        params: dict[str, Any] | None = None,
    ) -> tuple[list[Any], bool]:
        result: list[Any] = []
        for page in range(1, max_pages + 1):
            data = self.get(
                path, params={**(params or {}), "per_page": 100, "page": page}, fresh=fresh
            )
            items = data[key] if key else data
            if not isinstance(items, list):
                raise IntegrationError("GITHUB_SCHEMA", "Unexpected GitHub evidence format.")
            result.extend(items)
            if len(items) < 100:
                return result, True
        return result, False

    def resolve(self, ref: str) -> str:
        data = self.get(f"{self.prefix}/commits/{quote(ref, safe='')}", fresh=True)
        return str(data["sha"])

    def compare(self, base: str, head: str) -> dict[str, Any]:
        return dict(
            self.get(f"{self.prefix}/compare/{base}...{head}", params={"per_page": 100}, ttl=300)
        )
