from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(Path(__file__).resolve().parents[2] / ".env"), ".env"), extra="ignore"
    )

    database_url: str = (
        "postgresql+psycopg://releasepilot:releasepilot-local-only@localhost:5432/releasepilot"
    )
    database_host: str = ""
    database_password: SecretStr = SecretStr("")
    database_sslmode: str = "require"
    github_app_private_key: SecretStr = SecretStr("")
    agent_timeout_seconds: int = 120
    agent_token_budget: int = 32000
    agent_cost_budget_usd: float = 0.06
    model_max_usd_per_million_tokens: float = 1.6
    app_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_hours: int = 12
    demo_email: str = "demo@releasepilot.local"
    demo_password: str = ""
    environment: str = "local"
    redis_url: str = "redis://localhost:6379/0"
    aws_region: str = "us-west-2"
    aws_endpoint_url: str | None = None
    s3_bucket: str = "releasepilot-documents"
    sqs_queue_url: str = ""
    sqs_dlq_url: str = ""
    queue_backend: str = "database"
    object_backend: str = "local"
    local_object_dir: str = "/tmp/releasepilot-objects"
    github_app_id: str = ""
    github_app_slug: str = ""
    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    github_app_private_key_file: str = ""
    github_webhook_secret: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    mcp_url: str = "http://localhost:8001/mcp"
    internal_secret: SecretStr = SecretStr("")
    max_job_attempts: int = 5
    max_github_requests: int = 80
    max_upload_bytes: int = 5 * 1024 * 1024

    @model_validator(mode="after")
    def production_safety(self) -> Self:
        if self.database_host:
            from sqlalchemy import URL

            self.database_url = URL.create(
                "postgresql+psycopg",
                username="releasepilot",
                password=self.database_password.get_secret_value(),
                host=self.database_host,
                port=5432,
                database="releasepilot",
                query={"sslmode": self.database_sslmode},
            ).render_as_string(hide_password=False)
        if self.environment == "production":
            if not self.cookie_secure or not self.app_origin.startswith("https://"):
                raise ValueError("Production requires HTTPS and secure session cookies")
            if len(self.internal_secret.get_secret_value()) < 32:
                raise ValueError("Production requires a strong internal secret")
            if self.demo_password == "local-demo-change-me":
                raise ValueError("Replace the local demo password before deployment")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
