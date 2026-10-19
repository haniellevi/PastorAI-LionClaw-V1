"""API web editorial. Identidade/igreja vêm exclusivamente da autenticação."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services import conhecimento_editorial as service

router=APIRouter(prefix='/conhecimento',tags=['conhecimento'])
Publico = Literal['institucional_publico','membros','papel:admin','papel:pastor',
    'papel:lider_g12','papel:lider_consol','papel:lider_celula','papel:lider_mult',
    'papel:operador','papel:membro']


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operacao_id: UUID


class SnapshotInput(Input):
    versao_id: UUID
    conteudo: str=Field(min_length=1,max_length=100000)
    origem: str=Field(min_length=1,max_length=500)
    publicos: list[Publico]=Field(default_factory=list,max_length=10)

    @field_validator('conteudo','origem')
    @classmethod
    def nonempty(cls,value):
        if not value.strip(): raise ValueError('Informe texto não vazio')
        return value

    @field_validator('publicos')
    @classmethod
    def audience(cls,value):
        return sorted(set(value))


class CriarInput(SnapshotInput):
    id: UUID
    titulo: str=Field(min_length=1,max_length=200)
    assunto: str=Field(min_length=1,max_length=120)
    responsavel_id: UUID

    @field_validator('titulo','assunto')
    @classmethod
    def nonempty_label(cls,value):
        value=value.strip()
        if not value: raise ValueError('Informe texto não vazio')
        return value


class EditarInput(SnapshotInput):
    anterior_id: UUID


class AcaoInput(Input):
    versao_id: UUID


class PublicarInput(AcaoInput):
    publicos: list[Publico]=Field(min_length=1,max_length=10)
    # Required, including explicit null, to detect competing replacement.
    vigente_esperada_id: UUID | None

    @field_validator('publicos')
    @classmethod
    def audience(cls,value):
        return sorted(set(value))


DB=Depends(get_db)
USER=Depends(get_current_user)


@router.post('/documentos')
def criar(payload: CriarInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'criar',payload.id,payload)
    db.commit()
    return result


@router.post('/documentos/{did}/rascunhos')
def editar(did: UUID,payload: EditarInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'editar',did,payload)
    db.commit()
    return result


@router.post('/documentos/{did}/enviar-revisao')
def enviar(did: UUID,payload: AcaoInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'enviar-revisao',did,payload)
    db.commit()
    return result


@router.post('/documentos/{did}/revisar')
def revisar(did: UUID,payload: AcaoInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'revisar',did,payload)
    db.commit()
    return result


@router.post('/documentos/{did}/publicar')
def publicar(did: UUID,payload: PublicarInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'publicar',did,payload)
    db.commit()
    return result


@router.post('/documentos/{did}/revogar')
def revogar(did: UUID,payload: AcaoInput,db: Session=DB,user: CurrentUser=USER):
    result=service.executar(db,user,'revogar',did,payload)
    db.commit()
    return result


@router.get('/versoes/{vid}')
def ler(vid: UUID,db: Session=DB,user: CurrentUser=USER):
    return service.ler(db,user,vid)


@router.get('/busca')
def buscar(q: str=Query(min_length=1,max_length=200),
           limite: int=Query(default=10,ge=1,le=20),db: Session=DB,user: CurrentUser=USER):
    from app.services.conhecimento import buscar as busca_autorizada
    return busca_autorizada(db,user,q,limite)


@router.get('/documentos')
def listar(db: Session=DB,user: CurrentUser=USER):
    return service.painel(db,user)
