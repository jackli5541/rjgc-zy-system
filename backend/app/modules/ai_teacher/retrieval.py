from __future__ import annotations

import hashlib
import html
import markdown
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import AiKnowledgeChunk, AiKnowledgeNode, AiSubjectKnowledge, Assignment, SubmissionDocument, SubmissionWorkspace
from app.settings import settings


@dataclass
class RetrievedContext:
    source_type: str
    source_id: str | None
    source_title: str
    content: str
    score: float

    def json(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_title": self.source_title,
            "snippet": self.content[:600],
            "score": round(self.score, 4),
        }


def html_to_text(value: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\x00", "")).strip()


def normalize_reference_text(value: str, markdown_source: bool = False) -> str:
    """Normalize selected text and stored Markdown into the same searchable form."""
    if markdown_source:
        value = html_to_text(markdown.markdown(value or "", extensions=["tables", "fenced_code"]))
    return normalize_text(value).replace("\u3000", " ")


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chunk_text(value: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind(".", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [item for item in chunks if item]


def source_scope_filter(owner_user_id: UUID | None, owner_team_id: UUID | None):
    filters = [AiKnowledgeChunk.visibility == "PUBLIC_TO_STUDENT"]
    if owner_user_id:
        filters.append((AiKnowledgeChunk.visibility == "OWN_WORKSPACE") & (AiKnowledgeChunk.owner_user_id == owner_user_id))
    if owner_team_id:
        filters.append((AiKnowledgeChunk.visibility == "OWN_WORKSPACE") & (AiKnowledgeChunk.owner_team_id == owner_team_id))
    return or_(*filters)


def upsert_source_chunks(
    db: Session,
    assignment_id: UUID,
    source_type: str,
    source_id: str | None,
    source_title: str,
    text: str,
    visibility: str,
    owner_user_id: UUID | None = None,
    owner_team_id: UUID | None = None,
) -> None:
    source_key = source_id or source_type
    db.execute(
        delete(AiKnowledgeChunk).where(
            AiKnowledgeChunk.assignment_id == assignment_id,
            AiKnowledgeChunk.source_type == source_type,
            AiKnowledgeChunk.source_id == source_key,
            AiKnowledgeChunk.owner_user_id == owner_user_id,
            AiKnowledgeChunk.owner_team_id == owner_team_id,
        )
    )
    for index, chunk in enumerate(chunk_text(text)):
        db.add(AiKnowledgeChunk(
            assignment_id=assignment_id,
            owner_user_id=owner_user_id,
            owner_team_id=owner_team_id,
            source_type=source_type,
            source_id=source_key,
            source_title=source_title,
            visibility=visibility,
            chunk_index=index,
            content=chunk,
            content_hash=content_hash(chunk),
        ))


def refresh_assignment_ai_chunks(
    db: Session,
    assignment: Assignment,
    workspace: SubmissionWorkspace | None = None,
) -> None:
    public_text = f"{assignment.title}\n\n{html_to_text(assignment.description)}"
    upsert_source_chunks(db, assignment.id, "ASSIGNMENT_DESCRIPTION", "assignment", "作业说明", public_text, "PUBLIC_TO_STUDENT")
    if not workspace:
        return
    db.execute(
        delete(AiKnowledgeChunk).where(
            AiKnowledgeChunk.assignment_id == assignment.id,
            AiKnowledgeChunk.visibility == "OWN_WORKSPACE",
            AiKnowledgeChunk.owner_user_id == workspace.owner_user_id,
            AiKnowledgeChunk.owner_team_id == workspace.owner_team_id,
        )
    )
    documents = db.scalars(
        select(SubmissionDocument)
        .where(SubmissionDocument.workspace_id == workspace.id)
        .order_by(SubmissionDocument.sort_order, SubmissionDocument.created_at)
    ).all()
    for document in documents:
        upsert_source_chunks(
            db,
            assignment.id,
            "OWN_WORKSPACE",
            str(document.id),
            f"我的草稿：{document.name}",
            document.markdown_content or "",
            "OWN_WORKSPACE",
            workspace.owner_user_id,
            workspace.owner_team_id,
        )


def keyword_score(query: str, content: str) -> float:
    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()))
    if not query_terms:
        return 0
    content_lower = content.lower()
    hits = sum(1 for term in query_terms if term in content_lower)
    density = min(1.0, len(query) / max(len(content), 1))
    return hits / len(query_terms) + density * 0.05


def retrieve_contexts(
    db: Session,
    assignment_id: UUID,
    question: str,
    owner_user_id: UUID | None,
    owner_team_id: UUID | None,
    limit: int = 5,
) -> list[RetrievedContext]:
    rows = db.scalars(
        select(AiKnowledgeChunk)
        .where(AiKnowledgeChunk.assignment_id == assignment_id, source_scope_filter(owner_user_id, owner_team_id))
    ).all()
    scored = [
        RetrievedContext(row.source_type, row.source_id, row.source_title, row.content, keyword_score(question, row.content))
        for row in rows
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    selected = [item for item in scored if item.score > 0][:limit]
    if selected:
        return selected
    return scored[: min(limit, 3)]


def retrieve_subject_contexts(db: Session, class_id: UUID, subject: str, question: str, limit: int = 2) -> list[RetrievedContext]:
    rows = db.scalars(select(AiSubjectKnowledge).where(AiSubjectKnowledge.class_id == class_id)).all()
    scored = [
        RetrievedContext("SUBJECT_KNOWLEDGE", str(row.id), row.title, row.content[:900], keyword_score(question, row.content))
        for row in rows
    ]
    nodes = db.scalars(select(AiKnowledgeNode).where(
        AiKnowledgeNode.subject == subject, AiKnowledgeNode.visibility == "PUBLIC_TO_STUDENT",
    )).all()
    scored.extend(
        RetrievedContext("SUBJECT_KNOWLEDGE", str(row.id), row.title, row.content[:900], keyword_score(question, row.title + " " + row.summary + " " + row.content))
        for row in nodes
    )
    scored.sort(key=lambda item: item.score, reverse=True)
    return [item for item in scored if item.score > 0][:limit]


def build_context_block(contexts: list[RetrievedContext]) -> str:
    budget = settings.ai_teacher_max_context_chars
    pieces = []
    used = 0
    for index, item in enumerate(contexts, 1):
        content = item.content[: max(0, budget - used)]
        if not content:
            break
        piece = f"[{index}] 来源：{item.source_title}\n{content}"
        pieces.append(piece)
        used += len(piece)
        if used >= budget:
            break
    return "\n\n".join(pieces)
