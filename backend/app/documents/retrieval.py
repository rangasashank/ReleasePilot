import hashlib
import math
import re
import uuid
from collections import defaultdict
from io import BytesIO
from typing import Any

from openai import OpenAI
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import IntegrationError
from app.models import Document, DocumentChunk

DEMO_EMBEDDING = "demo-hash-v1"


def embed(texts: list[str], model: str) -> list[list[float]]:
    if model == DEMO_EMBEDDING:
        vectors = []
        for text in texts:
            vector = [0.0] * 1536
            for word in re.findall(r"\w+", text.lower()):
                digest = hashlib.sha256(word.encode()).digest()
                vector[int.from_bytes(digest[:4]) % 1536] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors
    settings = get_settings()
    if not settings.openai_api_key.get_secret_value():
        raise IntegrationError(
            "MODEL_NOT_CONFIGURED", "Configure an OpenAI API key for semantic embeddings."
        )
    client = OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=30, max_retries=1)
    result = client.embeddings.create(model=model, input=texts, dimensions=1536)
    return [item.embedding for item in sorted(result.data, key=lambda item: item.index)]


def extract(content: bytes, extension: str) -> list[tuple[str, int | None]]:
    pages: list[tuple[str, int | None]]
    if extension == ".pdf":
        if not content.startswith(b"%PDF"):
            raise IntegrationError("INVALID_FILE", "The file is not a PDF.")
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise IntegrationError(
                    "UNSUPPORTED_PDF", "Use an unencrypted PDF with at most 100 pages."
                )
            pages = [(page.extract_text() or "", i + 1) for i, page in enumerate(reader.pages)]
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError("INVALID_FILE", "PDF text extraction failed.") from exc
    else:
        try:
            pages = [(content.decode("utf-8"), None)]
        except UnicodeDecodeError as exc:
            raise IntegrationError("INVALID_ENCODING", "Text runbooks must use UTF-8.") from exc
    if not any(text.strip() for text, _ in pages):
        raise IntegrationError(
            "NO_TEXT", "No text found. Image-only PDFs and OCR are not supported."
        )
    if sum(len(text) for text, _ in pages) > 300_000:
        raise IntegrationError("DOCUMENT_TOO_LARGE", "Extracted text exceeds 300,000 characters.")
    return pages


def chunk_pages(pages: list[tuple[str, int | None]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for text, page in pages:
        heading = "Document"
        for section in re.split(r"(?m)(?=^#{1,6}\s)", text):
            lines = section.splitlines()
            if lines and re.match(r"^#{1,6}\s", lines[0]):
                heading = lines[0].lstrip("# ")[:500]
            # Approximately 500–800 tokens for ordinary English, with bounded overlap.
            words = section.split()
            for start in range(0, len(words), 420):
                body = " ".join(words[start : start + 500])
                if body:
                    chunks.append({"content": body, "heading": heading, "page": page})
                if start + 500 >= len(words):
                    break
    if len(chunks) > 200:
        raise IntegrationError("DOCUMENT_TOO_LARGE", "Runbook exceeds 200 chunks.")
    return chunks


def search(
    db: Session, workspace_id: uuid.UUID, service_id: uuid.UUID, query: str, top_k: int = 5
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    active = (
        select(DocumentChunk)
        .join(Document)
        .where(
            Document.workspace_id == workspace_id,
            Document.service_id == service_id,
            Document.deleted.is_(False),
            Document.status == "READY",
        )
    )
    models = db.scalars(
        select(Document.embedding_model)
        .where(
            Document.workspace_id == workspace_id,
            Document.service_id == service_id,
            Document.deleted.is_(False),
            Document.status == "READY",
        )
        .distinct()
    ).all()
    scores: dict[uuid.UUID, float] = defaultdict(float)
    records: dict[uuid.UUID, DocumentChunk] = {}
    postgres = db.get_bind().dialect.name == "postgresql"
    for model in models:
        vector = embed([query[:2000]], model)[0]
        if postgres:
            candidates = db.scalars(
                active.where(Document.embedding_model == model)
                .order_by(DocumentChunk.embedding.cosine_distance(vector))
                .limit(20)
            ).all()
        else:
            all_chunks = db.scalars(active.where(Document.embedding_model == model)).all()
            candidates = sorted(
                all_chunks,
                key=lambda row: -sum(a * b for a, b in zip(row.embedding, vector, strict=True)),
            )[:20]
        candidates = [
            row
            for row in candidates
            if sum(float(a) * b for a, b in zip(row.embedding, vector, strict=True)) >= 0.15
        ]
        for rank, row in enumerate(candidates, 1):
            records[row.id] = row
            scores[row.id] += 1 / (60 + rank)
    if postgres:
        tsquery = func.plainto_tsquery("english", query[:2000])
        document_vector = func.to_tsvector("english", DocumentChunk.content)
        lexical = db.scalars(
            active.where(document_vector.op("@@")(tsquery))
            .order_by(func.ts_rank(document_vector, tsquery).desc())
            .limit(20)
        ).all()
    else:
        words = set(re.findall(r"\w+", query.lower()))
        lexical = sorted(
            db.scalars(active).all(), key=lambda row: -len(words & set(row.content.lower().split()))
        )[:20]
    if not postgres:
        lexical = [row for row in lexical if words & set(re.findall(r"\w+", row.content.lower()))]
    for rank, row in enumerate(lexical, 1):
        records[row.id] = row
        scores[row.id] += 1 / (60 + rank)
    result = []
    for chunk_id in sorted(scores, key=lambda item: (-scores[item], str(item)))[
        : max(1, min(top_k, 5))
    ]:
        row = records[chunk_id]
        doc = db.get(Document, row.document_id)
        assert doc
        result.append(
            {
                "chunk_id": str(row.id),
                "document_id": str(doc.id),
                "title": doc.title,
                "heading": row.heading,
                "page": row.page,
                "excerpt": row.content,
                "embedding_model": doc.embedding_model,
                "score": round(scores[row.id], 6),
            }
        )
    return result
