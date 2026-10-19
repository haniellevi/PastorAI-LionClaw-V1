"""Authenticated UV panel API: attendance, validated milestones and completion."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.services import uv
from app.domain.uv import ModalidadeAula

router = APIRouter(prefix='/uv/turmas', tags=['uv'])


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TurmaInput(Input):
    id: UUID
    nome: str = Field(min_length=1, max_length=120)

    @field_validator('nome')
    @classmethod
    def name(cls, value):
        if not value.strip():
            raise ValueError('Informe o nome')
        return value.strip()


class Atividade(Input):
    ordem: int = Field(ge=1, le=9, strict=True)
    tipo: Literal['aula', 'encontro']
    aula: int | None = Field(default=None, ge=1, le=8, strict=True)
    data: date


class CalendarioInput(Input):
    atividades: list[Atividade] = Field(min_length=9, max_length=9)

    @model_validator(mode='after')
    def schedule(self):
        ordered = sorted(self.atividades, key=lambda a: a.ordem)
        expected = [('aula', n) for n in range(1, 5)] + [('encontro', None)] + [('aula', n) for n in range(5, 9)]
        if [(a.ordem, a.tipo, a.aula) for a in ordered] != [(i, *v) for i, v in enumerate(expected, 1)]:
            raise ValueError('Calendário exige aulas 1–4, Encontro e aulas 5–8, nessa ordem')
        if any(a.data > b.data for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Datas devem seguir a ordem das atividades')
        return self


class ResponsaveisInput(Input):
    usuarios: list[UUID] = Field(max_length=50)

    @field_validator('usuarios')
    @classmethod
    def unique(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('Responsáveis duplicados')
        return values


class MatriculaInput(Input):
    id: UUID
    pessoa_id: UUID


@router.get('')
def list_turmas(db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    return uv.list_turmas(db, user)


@router.post('')
def create(payload: TurmaInput, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.create_turma(db, user, payload)
    db.commit()
    return result


@router.get('/opcoes')
def options(q: str = Query(default='', max_length=120), finalidade: Literal['pessoas', 'usuarios'] = 'pessoas', db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    return uv.options(db, user, q, finalidade)


@router.get('/{turma_id}')
def detail(turma_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    return uv.get_turma(db, user, turma_id)


@router.put('/{turma_id}/calendario')
def calendar(turma_id: UUID, payload: CalendarioInput, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.calendar(db, user, turma_id, payload)
    db.commit()
    return result


@router.put('/{turma_id}/responsaveis')
def responsible(turma_id: UUID, payload: ResponsaveisInput, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.responsaveis(db, user, turma_id, payload)
    db.commit()
    return result


@router.post('/{turma_id}/matriculas')
def enroll(turma_id: UUID, payload: MatriculaInput, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.enroll(db, user, turma_id, payload)
    db.commit()
    return result


@router.post('/{turma_id}/encerrar')
def close(turma_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.close(db, user, turma_id)
    db.commit()
    return result


@router.post('/{turma_id}/reabrir')
def reopen(turma_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen("universidade-vida"))):
    result = uv.reopen(db, user, turma_id)
    db.commit()
    return result


class PresencaInput(Input):
    id: UUID
    presente: bool = Field(strict=True)
    modalidade: ModalidadeAula
    anterior_id: UUID | None = None


@router.post('/{turma_id}/matriculas/{matricula_id}/presencas/{aula}')
def attendance(turma_id: UUID, matricula_id: UUID, aula: int, payload: PresencaInput,
               db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen('universidade-vida'))):
    result = uv.attendance(db, user, turma_id, matricula_id, aula, payload)
    db.commit()
    return result


@router.get('/{turma_id}/matriculas/{matricula_id}/presencas/{aula}/historico')
def attendance_history(turma_id: UUID, matricula_id: UUID, aula: int,
                       db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen('universidade-vida'))):
    return uv.attendance_history(db, user, turma_id, matricula_id, aula)


class MarcoInput(Input):
    id: UUID
    data: date
    anterior_turma: bool = Field(strict=True)
    confirmado: bool = Field(strict=True)


class ConclusaoInput(Input):
    id: UUID
    confirmado: bool = Field(strict=True)


@router.post('/{turma_id}/matriculas/{matricula_id}/marcos/{tipo}')
def milestone(turma_id: UUID, matricula_id: UUID, tipo: Literal['encontro','batismo','reencontro'], payload: MarcoInput,
              db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen('universidade-vida'))):
    result = uv.milestone(db,user,turma_id,matricula_id,tipo,payload)
    db.commit()
    return result


@router.post('/{turma_id}/matriculas/{matricula_id}/concluir')
def finish(turma_id: UUID, matricula_id: UUID, payload: ConclusaoInput,
           db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen('universidade-vida'))):
    result = uv.finish(db,user,turma_id,matricula_id,payload)
    db.commit()
    return result


class RevogacaoMarcoInput(Input):
    motivo: str = Field(min_length=1, max_length=1000)


@router.post('/{turma_id}/matriculas/{matricula_id}/marcos/{tipo}/revogar')
def revoke_milestone(turma_id: UUID, matricula_id: UUID, tipo: Literal['reencontro'], payload: RevogacaoMarcoInput,
                     db: Session = Depends(get_db), user: CurrentUser = Depends(require_screen('universidade-vida'))):
    result = uv.revoke_milestone(db,user,turma_id,matricula_id,tipo,payload)
    db.commit()
    return result
