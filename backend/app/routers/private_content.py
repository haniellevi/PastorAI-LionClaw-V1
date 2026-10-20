"""Web-only administrative erasure; no pastoral SELECT required."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.services.private_deletion import delete_private, receipt

router = APIRouter(tags=['exclusao-privada'])


class ErasureApproval(BaseModel):
    operation_id: UUID
    confirmacao: Literal['EXCLUIR CONTEUDO PRIVADO']


@router.delete('/contacts/{pessoa_id}/private-content')
def erase_person(pessoa_id: UUID, approval: ErasureApproval,
                 db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    return delete_private(db, scope='pessoa', igreja_id=UUID(user.igreja_id),
                          target_id=pessoa_id, operation_id=approval.operation_id)


@router.delete('/igreja/private-content')
def erase_church(approval: ErasureApproval, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    tenant = UUID(user.igreja_id)
    return delete_private(db, scope='igreja', igreja_id=tenant, target_id=tenant,
                          operation_id=approval.operation_id)


@router.get('/igreja/private-deletions/{receipt_id}')
def progress(receipt_id: UUID, db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_role(['admin']))) -> dict:
    return receipt(db, UUID(user.igreja_id), receipt_id)
