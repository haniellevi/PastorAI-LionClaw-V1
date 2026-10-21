"""Gestão web sensível de responsabilidade; nenhum caller WhatsApp."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.services import responsabilidades as service

router = APIRouter(prefix='/responsabilidades', tags=['responsabilidades'])
Setor = Literal['atendimento','consolidacao','central_celulas','universidade_vida',
                'capacitacao_destino','agenda','conhecimento_oficial']


class AtribuicaoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pessoa_id: UUID
    setor: Setor
    inicio: date
    fim: date | None = None


class EncerramentoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fim: date


@router.get('')
def listar(em: date | None = None, setor: Setor | None = None,
           limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0),
           db: Session = Depends(get_db), user: CurrentUser = Depends(require_role(['pastor']))):
    return service.listar(db,user,em=em,setor=setor,limit=limit,offset=offset)


@router.post('', status_code=201)
def atribuir(payload: AtribuicaoInput, db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_role(['pastor']))):
    result = service.atribuir(db,user,payload)
    db.commit()
    return result


@router.post('/{responsabilidade_id}/encerrar')
def encerrar(responsabilidade_id: UUID, payload: EncerramentoInput,
             db: Session = Depends(get_db), user: CurrentUser = Depends(require_role(['pastor']))):
    result = service.encerrar(db,user,responsabilidade_id,payload.fim)
    db.commit()
    return result
