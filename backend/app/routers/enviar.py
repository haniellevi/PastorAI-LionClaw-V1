"""Sensitive Enviar evaluation is available only through authenticated web."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import CurrentUser, require_central
from app.services.enviar_avaliacoes import avaliacao_out, historico_pessoa, registrar_avaliacao

router = APIRouter(prefix='/enviar', tags=['enviar'])


class AvaliacaoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    decisao: Literal['apto', 'nao_apto']
    motivo: str = Field(min_length=1, max_length=300)
    origem: Literal['avaliacao', 'legado'] = 'avaliacao'
    solicitacao_id: UUID | None = None

    @field_validator('motivo')
    @classmethod
    def motivo_obrigatorio(cls, value):
        if not value.strip():
            raise ValueError('Informe o motivo da decisão')
        return value.strip()


@router.get('/pessoas/{pessoa_id}/avaliacoes')
def get_avaliacoes(pessoa_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_central)):
    return historico_pessoa(db, user, pessoa_id)


@router.post('/pessoas/{pessoa_id}/avaliacoes', status_code=201)
def post_avaliacao(pessoa_id: UUID, payload: AvaliacaoInput, db: Session = Depends(get_db), user: CurrentUser = Depends(require_central)):
    row = registrar_avaliacao(db, user, pessoa_id, payload)
    out = avaliacao_out(row)
    db.commit()
    return out
