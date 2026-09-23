import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)


class UserSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_service_workspace_name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReleaseCandidate(Base):
    __tablename__ = "release_candidates"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"))
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repositories.id"))
    base_ref: Mapped[str | None] = mapped_column(String(200))
    head_ref: Mapped[str | None] = mapped_column(String(200))
    base_sha: Mapped[str] = mapped_column(String(40))
    head_sha: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("workspace_id", "request_key", name="uq_analysis_request"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    release_candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("release_candidates.id"))
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    scenario: Mapped[str] = mapped_column(String(40))
    source_mode: Mapped[str] = mapped_column(String(20), default="demo")
    state: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    stale: Mapped[bool] = mapped_column(default=False, server_default="false")
    model_name: Mapped[str] = mapped_column(
        String(80), default="deterministic", server_default="deterministic"
    )
    policy_version: Mapped[str] = mapped_column(String(40))
    risk_score: Mapped[int]
    confidence_score: Mapped[int]
    recommendation: Mapped[str] = mapped_column(String(10))
    summary: Mapped[str] = mapped_column(String(1000))
    # JSON holds variable-shaped normalized facts and score explanations; child records
    # stay relational.
    input_facts: Mapped[dict[str, object]] = mapped_column(JSON)
    score_details: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    excerpt: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(2000))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingRecord(Base):
    __tablename__ = "findings"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id"), index=True)
    rule: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text)
    points: Mapped[int]
    position: Mapped[int]


class FindingCitation(Base):
    __tablename__ = "finding_citations"
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"), primary_key=True)
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), primary_key=True
    )


class ChecklistRecord(Base):
    __tablename__ = "checklist_items"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id"), index=True)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"))
    title: Mapped[str] = mapped_column(Text)
    required: Mapped[bool]
    status: Mapped[str] = mapped_column(String(20), default="open")
    position: Mapped[int]


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_repository"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    installation_id: Mapped[int | None] = mapped_column(BigInteger)
    github_id: Mapped[int] = mapped_column(BigInteger)
    full_name: Mapped[str] = mapped_column(String(200))
    default_branch: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="connected")
    auth_mode: Mapped[str] = mapped_column(String(20), default="app")
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(80))
    object_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    error_code: Mapped[str | None] = mapped_column(String(80))
    embedding_model: Mapped[str] = mapped_column(String(80))
    deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_document_chunk"),
        Index(
            "ix_chunks_search", text("to_tsvector('english', content)"), postgresql_using="gin"
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    heading: Mapped[str] = mapped_column(String(500))
    page: Mapped[int | None]
    embedding: Mapped[list[float]] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"))


class Job(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (Index("ix_jobs_due", "state", "next_attempt_at", "lease_expires_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analyses.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    operation_key: Mapped[str] = mapped_column(String(250), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="READY")
    stage: Mapped[str] = mapped_column(String(50), default="QUEUED")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    checkpoints: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("analysis_id", "agent_type", "input_hash", name="uq_agent_input"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id"), index=True)
    agent_type: Mapped[str] = mapped_column(String(30))
    input_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="RUNNING")
    output: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    model_name: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(default=0)
    token_count: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id"), index=True)
    agent_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int] = mapped_column(default=0)
    result: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="RECEIVED")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderQuota(Base):
    __tablename__ = "provider_rate_limits"
    installation_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    remaining: Mapped[int | None]
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(default=0)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GitHubGrant(Base):
    __tablename__ = "github_grants"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    installation_ids: Mapped[list[int]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
