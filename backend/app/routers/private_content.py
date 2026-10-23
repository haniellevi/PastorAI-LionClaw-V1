"""Web-only administrative erasure; no pastoral SELECT required."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Igreja
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers.operations import require_active_admin
from app.services.private_deletion import delete_private, receipt

router = APIRouter(tags=['exclusao-privada'])


class ErasureApproval(BaseModel):
    operation_id: UUID
    confirmacao: Literal['EXCLUIR CONTEUDO PRIVADO']


class ChurchErasureApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID
    nome_igreja: str
    confirmacao: Literal['EXCLUIR CONTEUDO PRIVADO DA IGREJA']


@router.delete('/contacts/{pessoa_id}/private-content')
def erase_person(pessoa_id: UUID, approval: ErasureApproval,
                 db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    return delete_private(db, scope='pessoa', igreja_id=UUID(user.igreja_id),
                          target_id=pessoa_id, operation_id=approval.operation_id)


@router.delete('/igreja/private-content')
def erase_church(approval: ChurchErasureApproval, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_active_admin)) -> dict:
    tenant = UUID(user.igreja_id)
    church_name = db.scalar(select(Igreja.nome).where(Igreja.id == tenant))
    if church_name is None or approval.nome_igreja != church_name:
        raise HTTPException(422, 'Confirmação nominal inválida')
    return delete_private(db, scope='igreja', igreja_id=tenant, target_id=tenant,
                          operation_id=approval.operation_id)


@router.get('/igreja/private-deletions/{receipt_id}')
def progress(receipt_id: UUID, db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_active_admin)) -> dict:
    return receipt(db, UUID(user.igreja_id), receipt_id)


class RequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal['aprovado', 'recusado']
    confirmacao: Literal['DECIDIR PEDIDO DE EXCLUSAO']


@router.get('/contacts/{pessoa_id}/private-erasure-requests')
def person_requests(pessoa_id: UUID, response: Response, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    from sqlalchemy import text
    from app.services import private_erasure_requests as requests
    response.headers['Cache-Control'] = 'private, no-store'
    tenant = UUID(user.igreja_id)
    ids = db.execute(
        text('select id from private_erasure_requests where igreja_id=:t and pessoa_id=:p '
             'order by created_at desc,id limit 50'),
        dict(t=tenant, p=pessoa_id),
    ).scalars().all()
    return {'items': [requests.detail(db, tenant, rid, include_sla=True) for rid in ids]}


@router.post('/private-erasure-requests/{request_id}/decision')
def decide_request(request_id: UUID, payload: RequestDecision, response: Response,
                   db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    from app.services import private_erasure_requests as requests
    response.headers['Cache-Control'] = 'private, no-store'
    return requests.decide(db, UUID(user.igreja_id), request_id, payload.decision)
