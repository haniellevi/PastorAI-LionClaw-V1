"""Authenticated CD panel: catalog, turmas, enrollment and attendance."""
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.domain.cd import AULAS_POR_MODULO, CurriculoCD, EVIDENCIA_MAX_CARACTERES
from app.routers.uv import Input, TurmaInput as NamedInput, ResponsaveisInput, MatriculaInput, PresencaInput
from app.services import cd

router=APIRouter(prefix='/cd',tags=['cd'])


class NomeInput(Input):
    nome: str = Field(min_length=1,max_length=120)

    @field_validator('nome')
    @classmethod
    def name(cls, value):
        return NamedInput.name(value)


class NivelInput(Input):
    nome: str = Field(min_length=1,max_length=120)
    modulos: list[Annotated[int, Field(strict=True,ge=1,le=100)]] = Field(min_length=1,max_length=100)


class CurriculoInput(NamedInput):
    versao: str = Field(min_length=1,max_length=80)
    niveis: list[NivelInput] = Field(default_factory=list,max_length=100)
    aulas_por_modulo: list[Annotated[int, Field(strict=True,ge=1,le=100)]] = Field(default_factory=lambda: list(AULAS_POR_MODULO),min_length=1,max_length=100)

    @model_validator(mode='after')
    def curriculum(self):
        self.versao=self.versao.strip()
        if any(not n.nome.strip() for n in self.niveis): raise ValueError('Informe o nome do nível')
        CurriculoCD(self.versao,tuple(self.aulas_por_modulo),niveis=tuple(tuple(n.modulos) for n in self.niveis))
        return self


class TurmaInput(NamedInput):
    curriculo_id: UUID
    modulo_id: UUID


class AulaData(Input):
    aula_id: UUID
    data: date


class CalendarioInput(Input):
    aulas: list[AulaData] = Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def unique(self):
        if len({a.aula_id for a in self.aulas})!=len(self.aulas): raise ValueError('Aulas duplicadas')
        return self


DB=Depends(get_db)
USER=Depends(require_screen('capacitacao'))


@router.get('/curriculos')
def curricula(db: Session=DB,user: CurrentUser=USER):
    return cd.list_curriculos(db,user)


@router.post('/curriculos')
def create_curriculum(payload: CurriculoInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.create_curriculo(db,user,payload); db.commit(); return result


@router.put('/curriculos/{cid}/{kind}/{record_id}')
def rename_curriculum(cid: UUID,kind: Literal['curriculo','nivel','modulo','aula'],record_id: UUID,payload: NomeInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.rename_catalog(db,user,cid,kind,record_id,payload); db.commit(); return result


@router.get('/opcoes')
def options(db: Session=DB,user: CurrentUser=USER):
    return cd.options(db,user)


@router.get('/turmas')
def turmas(db: Session=DB,user: CurrentUser=USER):
    return cd.list_turmas(db,user)


@router.post('/turmas')
def create(payload: TurmaInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.create_turma(db,user,payload); db.commit(); return result


@router.get('/turmas/{tid}')
def detail(tid: UUID,db: Session=DB,user: CurrentUser=USER):
    return cd.get_turma(db,user,tid)


@router.put('/turmas/{tid}')
def rename(tid: UUID,payload: NomeInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.rename_turma(db,user,tid,payload); db.commit(); return result


@router.put('/turmas/{tid}/calendario')
def calendar(tid: UUID,payload: CalendarioInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.calendar(db,user,tid,payload); db.commit(); return result


@router.put('/turmas/{tid}/responsaveis')
def responsible(tid: UUID,payload: ResponsaveisInput,db: Session=DB,user: CurrentUser=USER):
    result=cd.responsaveis(db,user,tid,payload); db.commit(); return result


@router.post('/turmas/{tid}/encerrar')
def close(tid: UUID,db: Session=DB,user: CurrentUser=USER):
    result=cd.close(db,user,tid); db.commit(); return result


@router.post('/turmas/{tid}/reabrir')
def reopen(tid: UUID,db: Session=DB,user: CurrentUser=USER):
    result=cd.close(db,user,tid,reopen=True); db.commit(); return result


@router.get('/turmas/{tid}/matriculas')
def enrollments(tid: UUID, db: Session=DB, user: CurrentUser=USER):
    return cd.list_enrollments(db, user, tid)


@router.get('/turmas/{tid}/elegiveis')
def eligible(tid: UUID, db: Session=DB, user: CurrentUser=USER,
             q: str=Query(default="", max_length=120),
             limit: int=Query(default=100, ge=1, le=100),
             offset: int=Query(default=0, ge=0)):
    return cd.eligible(db, user, tid, q=q, limit=limit, offset=offset)


@router.post('/turmas/{tid}/matriculas')
def enroll(tid: UUID, payload: MatriculaInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.enroll(db, user, tid, payload); db.commit(); return result


@router.post('/turmas/{tid}/matriculas/{mid}/cancelar')
def cancel_enrollment(tid: UUID, mid: UUID, db: Session=DB, user: CurrentUser=USER):
    result=cd.cancel_enrollment(db, user, tid, mid); db.commit(); return result


@router.post('/turmas/{tid}/matriculas/{mid}/presencas/{aula_id}')
def attendance(tid: UUID, mid: UUID, aula_id: UUID, payload: PresencaInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.attendance(db,user,tid,mid,aula_id,payload); db.commit(); return result


@router.get('/turmas/{tid}/matriculas/{mid}/presencas/{aula_id}/historico')
def attendance_history(tid: UUID, mid: UUID, aula_id: UUID, db: Session=DB, user: CurrentUser=USER):
    return cd.attendance_history(db,user,tid,mid,aula_id)


@router.get('/turmas/{tid}/frequencia')
def attendance_summary(tid: UUID, db: Session=DB, user: CurrentUser=USER):
    return cd.attendance_summary(db,user,tid)


class ConclusaoInput(Input):
    id: UUID
    confirmado: bool = Field(strict=True)


class EquivalenciaInput(ConclusaoInput):
    evidencia: str = Field(min_length=1,max_length=EVIDENCIA_MAX_CARACTERES)

    @field_validator('evidencia')
    @classmethod
    def evidence(cls,value):
        from app.domain.cd import evidencia_equivalencia
        return evidencia_equivalencia(value)


class RevogacaoInput(Input):
    motivo: str = Field(min_length=1,max_length=EVIDENCIA_MAX_CARACTERES)

    @field_validator('motivo')
    @classmethod
    def reason(cls,value):
        return EquivalenciaInput.evidence(value)


@router.post('/turmas/{tid}/matriculas/{mid}/conclusao')
def finish(tid: UUID, mid: UUID, payload: ConclusaoInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.finish(db,user,tid,mid,payload); db.commit(); return result


@router.post('/turmas/{tid}/matriculas/{mid}/equivalencia')
def equivalence(tid: UUID, mid: UUID, payload: EquivalenciaInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.finish(db,user,tid,mid,payload,equivalence=True); db.commit(); return result


@router.get('/pessoas/{pid}/curriculos/{cid}')
def progress(pid: UUID, cid: UUID, db: Session=DB, user: CurrentUser=USER):
    return cd.person_progress(db,user,pid,cid)


@router.post('/pessoas/{pid}/curriculos/{cid}/certificados')
def issue_certificate(pid: UUID, cid: UUID, payload: ConclusaoInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.issue_certificate(db,user,pid,cid,payload); db.commit(); return result


@router.post('/certificados/{cert_id}/revogar')
def revoke_certificate(cert_id: UUID, payload: RevogacaoInput, db: Session=DB, user: CurrentUser=USER):
    result=cd.revoke_certificate(db,user,cert_id,payload); db.commit(); return result
