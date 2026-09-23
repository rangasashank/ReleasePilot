import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, current_identity, mutation_identity
from app.config import get_settings
from app.db import get_db
from app.documents.retrieval import DEMO_EMBEDDING, search
from app.documents.storage import put_object
from app.jobs.state import enqueue
from app.models import Document
from app.services import get_service

router = APIRouter(prefix="/api/v1/documents", tags=["knowledge"])


def output(doc: Document) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "service_id": str(doc.service_id),
        "title": doc.title,
        "status": doc.status,
        "error_code": doc.error_code,
        "embedding_model": doc.embedding_model,
        "created_at": doc.created_at.isoformat(),
    }


@router.get("")
def documents(
    service_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    get_service(db, identity.workspace.id, service_id)
    return [
        output(d)
        for d in db.scalars(
            select(Document)
            .where(
                Document.workspace_id == identity.workspace.id,
                Document.service_id == service_id,
                Document.deleted.is_(False),
            )
            .order_by(Document.created_at.desc())
            .limit(100)
        )
    ]


@router.post("", status_code=202)
async def upload(
    service_id: uuid.UUID = Form(),
    file: UploadFile = File(),
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    get_service(db, identity.workspace.id, service_id)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in (".md", ".txt", ".pdf"):
        raise HTTPException(422, "Upload Markdown, UTF-8 text, or PDF")
    content = await file.read(get_settings().max_upload_bytes + 1)
    if not content or len(content) > get_settings().max_upload_bytes:
        raise HTTPException(413, "Use a nonempty document up to 5 MB")
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.workspace_id == identity.workspace.id,
            Document.service_id == service_id,
            Document.content_hash == digest,
            Document.deleted.is_(False),
            Document.status.in_(["QUEUED", "READY"]),
        )
    )
    if existing:
        return output(existing)
    document_id = uuid.uuid4()
    key = f"{identity.workspace.id}/{service_id}/{document_id}{extension}"
    put_object(key, content)
    settings = get_settings()
    doc = Document(
        id=document_id,
        workspace_id=identity.workspace.id,
        service_id=service_id,
        title=Path(file.filename or "Runbook").name[:200],
        media_type=extension,
        content_hash=digest,
        object_key=key,
        embedding_model=settings.embedding_model
        if settings.openai_api_key.get_secret_value()
        else DEMO_EMBEDDING,
    )
    db.add(doc)
    db.flush()
    enqueue(db, identity.workspace.id, "index", f"index:{doc.id}", {"document_id": str(doc.id)})
    db.commit()
    return output(doc)


@router.get("/search")
def retrieve(
    service_id: uuid.UUID,
    query: str = Query(min_length=1, max_length=2000),
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    get_service(db, identity.workspace.id, service_id)
    return search(db, identity.workspace.id, service_id, query)


@router.delete("/{document_id}", status_code=204)
def remove(
    document_id: uuid.UUID,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> None:
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.workspace_id == identity.workspace.id)
        .with_for_update()
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.deleted = True
    db.commit()


@router.post("/{document_id}/reindex", status_code=202)
def reindex(
    document_id: uuid.UUID,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == identity.workspace.id,
            Document.deleted.is_(False),
        )
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    replacement = Document(
        workspace_id=doc.workspace_id,
        service_id=doc.service_id,
        title=doc.title,
        media_type=doc.media_type,
        object_key=doc.object_key,
        content_hash=doc.content_hash,
        embedding_model=get_settings().embedding_model
        if get_settings().openai_api_key.get_secret_value()
        else DEMO_EMBEDDING,
    )
    db.add(replacement)
    db.flush()
    enqueue(
        db,
        identity.workspace.id,
        "index",
        f"index:{replacement.id}",
        {"document_id": str(replacement.id), "replaces": str(doc.id)},
    )
    db.commit()
    return output(replacement)
