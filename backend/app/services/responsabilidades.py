"""Responsável operacional por setor; não concede acesso. Caller faz commit.

Intervalos [inicio, fim): fim é o primeiro dia sem responsabilidade. A exclusão
GiST protege concorrência, inclusive entre atribuições de Pessoas diferentes.
"""
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from app.db.models import Pessoa


def _autor(db, user):
    tenant, uid = UUID(user.igreja_id), UUID(user.app_user_id)
    role = db.execute(text("""select r.papel from app_users u join user_roles r
        on r.igreja_id=u.igreja_id and r.user_id=u.id
        where u.igreja_id=:t and u.id=:u and u.status='ativo'
        and r.papel in ('admin','pastor') for share of u,r"""), dict(t=tenant,u=uid)).first()
    if role is None:
        raise HTTPException(403, 'Somente admin ou pastor pode gerir responsabilidades')
    return tenant, uid


def _rows(db, sql, **params):
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def vigentes_em(db, *, igreja_id: UUID, em: date, setor: str | None = None):
    """Consulta interna explícita por tenant; o caller autoriza o uso dos dados."""
    if not isinstance(igreja_id, UUID):
        raise ValueError('igreja_id deve ser UUID')
    return _rows(db, """select * from responsabilidades_setor where igreja_id=:t
        and inicio<=:em and (fim is null or fim>:em)
        and (:setor is null or setor=:setor) order by setor,inicio,id""",
        t=igreja_id, em=em, setor=setor)


def listar(db, user, *, em=None, setor=None, limit=50, offset=0):
    tenant, _ = _autor(db,user)
    return _rows(db, """select * from responsabilidades_setor where igreja_id=:t
        and (:em is null or (inicio<=cast(:em as date) and (fim is null or fim>cast(:em as date))))
        and (:setor is null or setor=:setor) order by setor,inicio,id limit :limit offset :offset""",
        t=tenant, em=em, setor=setor, limit=limit, offset=offset)


def atribuir(db, user, payload):
    tenant, uid = _autor(db,user)
    if payload.fim is not None and payload.fim <= payload.inicio:
        raise HTTPException(422, 'Fim deve ser posterior ao início')
    pessoa = db.scalar(select(Pessoa).where(Pessoa.igreja_id==tenant,
        Pessoa.id==payload.pessoa_id).with_for_update().execution_options(populate_existing=True))
    if pessoa is None or pessoa.arquivada_em is not None:
        raise HTTPException(404, 'Pessoa ativa não encontrada')
    try:
        with db.begin_nested():
            return _rows(db, """insert into responsabilidades_setor
                (igreja_id,pessoa_id,setor,inicio,fim,atribuida_por)
                values(:t,:p,:setor,:inicio,:fim,:u) returning *""",
                t=tenant,p=pessoa.id,setor=payload.setor,inicio=payload.inicio,fim=payload.fim,u=uid)[0]
    except IntegrityError as exc:
        if getattr(exc.orig,'pgcode',None)=='23P01':
            raise HTTPException(409, 'Setor já possui responsável no período') from exc
        raise


def encerrar(db, user, responsabilidade_id, fim):
    tenant, uid = _autor(db,user)
    found = _rows(db, """select * from responsabilidades_setor
        where igreja_id=:t and id=:id for update""", t=tenant,id=responsabilidade_id)
    if not found:
        raise HTTPException(404, 'Responsabilidade não encontrada')
    row = found[0]
    if row['encerrada_em'] is not None:
        if row['fim'] == fim:
            return row
        raise HTTPException(409, 'Responsabilidade já encerrada')
    if fim <= row['inicio'] or (row['fim'] is not None and fim > row['fim']):
        raise HTTPException(422, 'Encerramento deve reduzir a vigência sem eliminar o período')
    return _rows(db, """update responsabilidades_setor set fim=:fim,
        encerrada_por=:u,encerrada_em=clock_timestamp()
        where igreja_id=:t and id=:id returning *""", t=tenant,id=responsabilidade_id,fim=fim,u=uid)[0]
