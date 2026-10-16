"""Authenticated recipient panel. Screen visibility is not an authorization gate."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.prayer import policy, service

router = APIRouter(prefix="/prayer-requests", tags=["prayer-requests"])


class RequestOut(BaseModel):
    id: str
    summary: str
    pessoa_nome: str
    audience: str
    state: str
    created_at: str
    responsavel_id: str | None


def serialize(row, db):
    from app.db.models import Pessoa
    from sqlalchemy import select

    name = db.execute(
        select(Pessoa.nome).where(
            Pessoa.id == row.pessoa_id, Pessoa.igreja_id == row.igreja_id
        )
    ).scalar_one()
    return RequestOut(
        id=str(row.id),
        summary=row.summary,
        pessoa_nome=name or "Contato",
        audience=row.audience,
        state=row.state,
        created_at=row.created_at.isoformat(),
        responsavel_id=str(row.responsavel_id) if row.responsavel_id else None,
    )


def guard(user):
    if not policy.enabled(uuid.UUID(user.igreja_id)):
        raise HTTPException(404, "Recurso indisponível")


@router.get("/access")
def access(
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    if not policy.enabled(uuid.UUID(user.igreja_id)):
        return {"allowed": False}
    _, roles = service._actor(db, user)
    return {
        "allowed": bool(roles & policy.PASTORAL_ROLES)
        or bool(service.list_requests(db, user))
    }


@router.get("", response_model=list[RequestOut])
def list_items(
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    guard(user)
    response.headers["Cache-Control"] = "private, no-store"
    return [serialize(row, db) for row in service.list_requests(db, user)]


@router.get("/{request_id}", response_model=RequestOut)
def detail(
    request_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    guard(user)
    response.headers["Cache-Control"] = "private, no-store"
    return serialize(service.get_request(db, user, request_id), db)


@router.post("/{request_id}/assume", response_model=RequestOut)
def assume(
    request_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    guard(user)
    response.headers["Cache-Control"] = "private, no-store"
    row = service.assume(db, user, request_id)
    result = serialize(row, db)
    db.commit()
    return result


@router.post("/{request_id}/close", response_model=RequestOut)
def close(
    request_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    guard(user)
    response.headers["Cache-Control"] = "private, no-store"
    row = service.close(db, user, request_id)
    result = serialize(row, db)
    db.commit()
    return result
