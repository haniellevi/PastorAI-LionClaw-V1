"""Web-only private summary supervision. No aggregate/person lookup."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.services import private_summaries as service


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/conversations",
    tags=["private-summaries"],
    dependencies=[Depends(no_store)],
)


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    correction: str | None = Field(default=None, min_length=1, max_length=1000)
    incorrect: bool = False


def authorized(db, user, conversation):
    tenant = UUID(user.igreja_id)
    if (
        not user.has_any_role(["admin", "pastor"])
        or not db.execute(
            text("select private_summary_reader(:t,:c)"),
            dict(t=tenant, c=conversation),
        ).scalar_one()
    ):
        raise HTTPException(404, "Resumo indisponível")
    return tenant


@router.get("/{conversation}/private-summary")
def read(
    conversation: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_screen("inbox")),
):
    return service.read_summary(db, authorized(db, user, conversation), conversation)


@router.patch("/{conversation}/private-summary")
def correct(
    conversation: UUID,
    payload: Correction,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_screen("inbox")),
):
    tenant = authorized(db, user, conversation)
    if (
        not payload.incorrect
        and not db.execute(
            text("select private_summary_topic(:correction)"),
            dict(correction=payload.correction),
        ).scalar_one()
    ):
        raise HTTPException(422, "Correção deve ser uma dúvida operacional reconhecida")
    return service.correct_summary(
        db, tenant, conversation, payload.version, payload.correction, payload.incorrect
    )


@router.post("/{conversation}/private-summary/generate", status_code=202)
def generate(
    conversation: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_screen("inbox")),
):
    tenant = authorized(db, user, conversation)
    # HTTP has no direct task DML. SECURITY DEFINER performs the same reader
    # revalidation and source validation; the worker alone reserves/calls BYO.
    if not service.released(tenant):
        raise HTTPException(409, "Geração desativada")
    job = db.execute(
        text("select private_summary_enqueue(:c)"), dict(c=conversation)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(409, "Geração indisponível para esta origem")
    db.commit()
    return {"task_id": str(job)}
