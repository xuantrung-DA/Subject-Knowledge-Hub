from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.security import current_user
from app.errors import AppError
from app.rag import answer, create_summary_job

router = APIRouter(prefix="/api")


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=10000)
    conversation_id: str | None = None
    mode: Literal["direct", "assistant"] = "direct"
    retrieval_mode: Literal["dense", "lexical", "hybrid"] | None = None


class SummaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    confirmed: bool = False


@router.post("/subjects/{subject_id}/chat")
def chat(subject_id: str, body: ChatBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return answer(db, user.id, subject_id, **body.model_dump())
    except AppError:
        # Preserve real usage from earlier successful calls when a later call
        # fails. No assistant success message is inserted on failure.
        db.commit()
        raise


@router.post("/subjects/{subject_id}/documents/{document_id}/summary")
def summary(
    subject_id: str,
    document_id: str,
    body: SummaryBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return create_summary_job(db, user.id, subject_id, document_id, **body.model_dump())
